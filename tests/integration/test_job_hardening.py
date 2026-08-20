from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread
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
from app.knowledge.ingestion import KnowledgeIngestionHandler
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
    engine.dispose()
