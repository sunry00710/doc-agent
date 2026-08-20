from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.db.base import Base
from app.identity.models import User
from app.jobs.models import Job, JobStatus
from app.jobs.runner import JobHandler, JobRegistry, Worker
from app.jobs.service import claim_next_job, enqueue, finish_job, recover_stale_jobs
from app.knowledge.ingestion import JobClaimLostError, KnowledgeIngestionHandler
from app.knowledge.schemas import IngestionJobPayload
from app.projects import models as project_models  # noqa: F401
from run_worker import build_registry, create_worker


class Payload(BaseModel):
    value: str


class ContextHandler(JobHandler):
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def run(self, payload: dict) -> dict:
        self.calls.append(payload)
        return {"value": payload["value"]}


def make_factory(tmp_path: Path, name: str, timeout: float = 5):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"timeout": timeout, "check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_enqueue_rejects_non_model_and_reserved_context(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "enqueue.db")
    with factory() as session:
        owner = User(username="enqueue-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        with pytest.raises(TypeError, match="BaseModel"):
            enqueue(session, "context", {"value": "raw"}, owner.id, "raw")

        class SpoofedPayload(BaseModel):
            value: str
            _job_context: dict = {"claim_token": "spoofed"}

        with pytest.raises(ValueError, match="reserved"):
            enqueue(session, "context", SpoofedPayload(value="spoofed"), owner.id, "spoofed")
    engine.dispose()


def test_stale_reexecution_has_stable_identity_and_new_claim_token(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "context.db")
    calls: list[dict] = []
    registry = JobRegistry()
    registry.register("context", ContextHandler(calls))
    with factory() as session:
        owner = User(username="context-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        job = enqueue(session, "context", Payload(value="stable"), owner.id, "context-key")
        session.commit()
        first = claim_next_job(session, "stale-worker")
        assert first is not None and first.claim_token is not None
        old_token = first.claim_token
        first.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
        assert recover_stale_jobs(session, datetime.now(UTC), stale_after_seconds=60, max_attempts=3) == 1
        session.commit()

    assert Worker(factory, registry).run_once() is True
    context = calls[0]["_job_context"]
    assert context == {
        "job_id": job.id,
        "idempotency_key": "context-key",
        "attempt": 2,
        "claim_token": context["claim_token"],
    }
    assert context["claim_token"] != old_token
    with factory() as session:
        assert finish_job(session, job.id, old_token, {"value": "late"}) is False
        session.commit()
        persisted = session.get(Job, job.id)
        assert persisted is not None and persisted.status is JobStatus.succeeded
    engine.dispose()


def test_worker_requires_factory(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "factory.db")
    with factory() as session, pytest.raises(TypeError, match="session factory"):
        Worker(session, JobRegistry())
    engine.dispose()


def test_contended_sqlite_workers_do_not_crash_or_duplicate_claims(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "contended.db", timeout=0.01)
    handled: list[str] = []
    handled_lock = Lock()

    class RecordingHandler(JobHandler):
        def run(self, payload: dict) -> dict:
            with handled_lock:
                handled.append(payload["_job_context"]["job_id"])
            return {"value": payload["value"]}

    registry = JobRegistry()
    registry.register("record", RecordingHandler())
    with factory() as session:
        owner = User(username="contended-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        jobs = [enqueue(session, "record", Payload(value=str(i)), owner.id, f"key-{i}") for i in range(4)]
        session.commit()

    barrier = Barrier(2)
    errors: list[Exception] = []

    def run_worker(worker_id: str) -> None:
        worker = Worker(factory, registry, worker_id=worker_id, sqlite_lock_retries=5, sqlite_lock_backoff_seconds=0)
        barrier.wait()
        try:
            for _ in range(8):
                worker.run_once()
        except Exception as exc:  # noqa: BLE001 - assert concurrent workers surface no failure
            errors.append(exc)

    threads = [Thread(target=run_worker, args=(f"worker-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    assert sorted(handled) == sorted(job.id for job in jobs)
    assert len(handled) == len(set(handled))
    engine.dispose()


def test_run_forever_recovers_expected_lock_error(monkeypatch, tmp_path: Path):
    engine, factory = make_factory(tmp_path, "loop.db")
    worker = Worker(factory, JobRegistry())
    calls = 0
    sleeps: list[float] = []

    def run_once() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "run_once", run_once)
    with pytest.raises(KeyboardInterrupt):
        worker.run_forever(0.25, sleeper=sleeps.append)
    assert sleeps == [0.25]
    engine.dispose()


def test_worker_entrypoint_registers_knowledge_ingestion_handler(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "entrypoint.db")
    registry = build_registry(factory, None)
    assert isinstance(registry.get("knowledge.ingest"), KnowledgeIngestionHandler)
    assert isinstance(create_worker(engine).registry.get("knowledge.ingest"), KnowledgeIngestionHandler)
    engine.dispose()


def test_ingestion_handler_rejects_spoofed_or_missing_worker_context(tmp_path: Path):
    engine, factory = make_factory(tmp_path, "handler-context.db")
    handler = KnowledgeIngestionHandler(factory, None)
    payload = IngestionJobPayload(version_id=UUID("00000000-0000-0000-0000-000000000001"), space_id=UUID("00000000-0000-0000-0000-000000000002"))
    with pytest.raises(ValueError, match="_job_context"):
        handler.run(payload.model_dump())
    with pytest.raises(ValueError, match="_job_context"):
        handler.run({**payload.model_dump(), "_job_context": {"job_id": "x", "idempotency_key": "key", "attempt": 1}})
    with pytest.raises(ValueError, match="_job_context"):
        handler.run({**payload.model_dump(), "_job_context": {"job_id": "x", "idempotency_key": "key", "attempt": "1", "claim_token": "token"}})
    with pytest.raises(ValueError, match="_job_context"):
        handler.run({**payload.model_dump(), "_job_context": {"job_id": "x", "idempotency_key": "key", "attempt": 1, "claim_token": "token", "extra": "field"}})
    engine.dispose()


def test_worker_delivers_enqueue_json_uuid_payload_to_ingestion_handler(tmp_path: Path, monkeypatch):
    engine, factory = make_factory(tmp_path, "ingestion-json-payload.db")
    captured: dict[str, UUID] = {}
    handler = KnowledgeIngestionHandler(factory, object())

    def ingest(session, storage, version_id: UUID, space_id: UUID):
        captured.update(version_id=version_id, space_id=space_id)
        return SimpleNamespace(active_generation_id="generation-id")

    monkeypatch.setattr("app.knowledge.ingestion.ingest_version", ingest)
    registry = JobRegistry()
    registry.register("knowledge.ingest", handler)
    payload = IngestionJobPayload(version_id=UUID("00000000-0000-0000-0000-000000000001"), space_id=UUID("00000000-0000-0000-0000-000000000002"))
    with factory() as session:
        owner = User(username="ingestion-json-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        job = enqueue(session, "knowledge.ingest", payload, owner.id, "ingestion-json-key")
        session.commit()
        assert isinstance(job.payload["version_id"], str)
        assert isinstance(job.payload["space_id"], str)

    assert Worker(factory, registry).run_once() is True
    assert captured == {"version_id": payload.version_id, "space_id": payload.space_id}
    with factory() as session:
        persisted = session.get(Job, job.id)
        assert persisted is not None and persisted.status is JobStatus.succeeded
        assert persisted.result == {
            "version_id": str(payload.version_id),
            "space_id": str(payload.space_id),
            "generation_id": "generation-id",
            "job_id": job.id,
            "idempotency_key": "ingestion-json-key",
            "attempt": 1,
        }
        assert "claim_token" not in persisted.result
    engine.dispose()


def test_ingestion_handler_fences_reclaimed_claim_before_indexing(tmp_path: Path, monkeypatch):
    engine, factory = make_factory(tmp_path, "ingestion-claim-fencing.db")
    handler = KnowledgeIngestionHandler(factory, object())
    calls: list[str] = []

    def ingest(session, storage, version_id: UUID, space_id: UUID):
        calls.append(str(version_id))
        return SimpleNamespace(active_generation_id="generation-id")

    monkeypatch.setattr("app.knowledge.ingestion.ingest_version", ingest)
    payload = IngestionJobPayload(version_id=UUID("00000000-0000-0000-0000-000000000001"), space_id=UUID("00000000-0000-0000-0000-000000000002"))
    with factory() as session:
        owner = User(username="ingestion-fencing-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        job = enqueue(session, "knowledge.ingest", payload, owner.id, "ingestion-fencing-key")
        session.commit()
        old_claim = claim_next_job(session, "old-worker")
        assert old_claim is not None and old_claim.claim_token is not None
        old_token = old_claim.claim_token
        old_claim.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
        assert recover_stale_jobs(session, datetime.now(UTC), stale_after_seconds=60, max_attempts=3) == 1
        session.commit()
        current_claim = claim_next_job(session, "current-worker")
        assert current_claim is not None and current_claim.claim_token is not None
        current_token = current_claim.claim_token
        session.commit()

    old_payload = {**payload.model_dump(mode="json"), "_job_context": {"job_id": job.id, "idempotency_key": job.idempotency_key, "attempt": 1, "claim_token": old_token}}
    with pytest.raises(JobClaimLostError):
        handler.run(old_payload)
    assert calls == []

    result = handler.run({**old_payload, "_job_context": {**old_payload["_job_context"], "attempt": 2, "claim_token": current_token}})
    assert calls == [str(payload.version_id)]
    assert result == {
        "version_id": str(payload.version_id),
        "space_id": str(payload.space_id),
        "generation_id": "generation-id",
        "job_id": job.id,
        "idempotency_key": job.idempotency_key,
        "attempt": 2,
    }
    engine.dispose()


def test_worker_rejects_unsupported_ingestion_payload_version_without_ingesting(tmp_path: Path, monkeypatch):
    engine, factory = make_factory(tmp_path, "unsupported-ingestion-version.db")
    called = False
    handler = KnowledgeIngestionHandler(factory, object())

    def ingest(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unsupported payload version must not ingest")

    monkeypatch.setattr("app.knowledge.ingestion.ingest_version", ingest)
    registry = JobRegistry()
    registry.register("knowledge.ingest", handler)
    with factory() as session:
        owner = User(username="unsupported-ingestion-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        job = enqueue(
            session,
            "knowledge.ingest",
            IngestionJobPayload(version_id=UUID("00000000-0000-0000-0000-000000000001"), space_id=UUID("00000000-0000-0000-0000-000000000002")),
            owner.id,
            "unsupported-ingestion-key",
        )
        job.payload = {**job.payload, "payload_version": 2}
        session.commit()

    assert Worker(factory, registry).run_once() is True
    assert called is False
    with factory() as session:
        persisted = session.get(Job, job.id)
        assert persisted is not None and persisted.status is JobStatus.failed
    engine.dispose()
