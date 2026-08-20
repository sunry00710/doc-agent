from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import User
from app.jobs.models import Job, JobStatus
from app.jobs.runner import JobHandler, JobRegistry, Worker
from app.jobs.service import (
    RetryableJobError,
    cancel_job,
    claim_next_job,
    enqueue,
    heartbeat,
    recover_stale_jobs,
)
from app.main import create_app


class Payload(BaseModel):
    value: str


class ResultHandler(JobHandler):
    def run(self, payload: dict) -> dict:
        return {"value": payload["value"]}


class RetryableHandler(JobHandler):
    def run(self, payload: dict) -> dict:
        raise RetryableJobError("temporary failure")


class PermanentHandler(JobHandler):
    def run(self, payload: dict) -> dict:
        raise ValueError("secret handler detail")


class BlockingHandler(JobHandler):
    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release

    def run(self, payload: dict) -> dict:
        self.started.set()
        assert self.release.wait(timeout=2)
        return {"value": payload["value"]}


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def owner(db_session: Session) -> User:
    user = User(username="job-owner", password_hash=hash_password("correct"))
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def registry() -> JobRegistry:
    registry = JobRegistry()
    registry.register("result", ResultHandler())
    registry.register("retry", RetryableHandler())
    registry.register("permanent", PermanentHandler())
    return registry


def test_enqueue_returns_existing_job_for_scoped_idempotency_key(db_session, owner):
    first = enqueue(db_session, "result", Payload(value="one"), owner.id, "same-key")
    db_session.commit()
    second = enqueue(db_session, "result", Payload(value="two"), owner.id, "same-key")

    assert second.id == first.id
    assert second.payload == {"value": "one"}
    assert second.status is JobStatus.queued


def test_idempotency_key_is_unique_per_owner_and_type(db_session, owner):
    other = User(username="other-owner", password_hash=hash_password("correct"))
    db_session.add(other)
    db_session.commit()
    enqueue(db_session, "result", Payload(value="one"), owner.id, "same-key")
    enqueue(db_session, "other", Payload(value="two"), owner.id, "same-key")
    enqueue(db_session, "result", Payload(value="three"), other.id, "same-key")
    db_session.commit()

    duplicate = Job(
        job_type="result", payload={"value": "four"}, owner_id=owner.id, idempotency_key="same-key"
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_worker_completes_job_and_persists_structured_result(db_session, owner, registry):
    job = enqueue(db_session, "result", Payload(value="done"), owner.id, "success")
    db_session.commit()

    assert Worker(db_session, registry, max_attempts=3).run_once() is True
    db_session.refresh(job)
    assert job.status is JobStatus.succeeded
    assert job.attempts == 1
    assert job.result == {"value": "done"}
    assert job.error is None


def test_retryable_failure_schedules_bounded_retry(db_session, owner, registry):
    job = enqueue(db_session, "retry", Payload(value="retry"), owner.id, "retryable")
    db_session.commit()

    Worker(db_session, registry, max_attempts=2, retry_delay_seconds=10).run_once()
    db_session.refresh(job)
    assert job.status is JobStatus.retrying
    assert job.attempts == 1
    assert job.next_attempt_at is not None
    assert job.error == {"code": "retryable_failure", "message": "Job execution failed"}

    job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    Worker(db_session, registry, max_attempts=2).run_once()
    db_session.refresh(job)
    assert job.status is JobStatus.failed
    assert job.attempts == 2


def test_non_retryable_failure_is_safe_and_terminal(db_session, owner, registry):
    job = enqueue(db_session, "permanent", Payload(value="private"), owner.id, "permanent")
    db_session.commit()

    Worker(db_session, registry).run_once()
    db_session.refresh(job)
    assert job.status is JobStatus.failed
    assert job.error == {"code": "job_failed", "message": "Job execution failed"}
    assert "secret" not in str(job.error)


def test_cancel_before_start_prevents_claim(db_session, owner):
    job = enqueue(db_session, "result", Payload(value="cancel"), owner.id, "cancel")
    db_session.commit()

    assert cancel_job(db_session, job.id, owner.id) is True
    db_session.commit()
    assert claim_next_job(db_session, "worker-a") is None
    db_session.refresh(job)
    assert job.status is JobStatus.cancelled


def test_claim_is_atomic_and_terminal_jobs_are_not_claimable(db_session, owner):
    job = enqueue(db_session, "result", Payload(value="claim"), owner.id, "claim")
    db_session.commit()

    first = claim_next_job(db_session, "worker-a")
    second = claim_next_job(db_session, "worker-b")
    db_session.commit()
    assert first is not None
    assert second is None
    assert first.id == job.id
    assert first.claim_token is not None


def test_heartbeat_requires_current_claim_token(db_session, owner):
    enqueue(db_session, "result", Payload(value="heartbeat"), owner.id, "heartbeat")
    db_session.commit()
    claimed = claim_next_job(db_session, "worker-a")
    assert claimed is not None and claimed.claim_token is not None
    prior = claimed.heartbeat_at

    assert heartbeat(db_session, claimed.id, "other-token") is False
    assert heartbeat(db_session, claimed.id, claimed.claim_token) is True
    db_session.commit()
    db_session.refresh(claimed)
    assert claimed.heartbeat_at is not None and claimed.heartbeat_at >= prior


def test_worker_renews_heartbeat_while_handler_runs(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}", connect_args={"timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        owner = User(username="heartbeat-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.commit()
        job = enqueue(session, "blocking", Payload(value="heartbeat"), owner.id, "renew")
        session.commit()
        started, release = Event(), Event()
        registry = JobRegistry()
        registry.register("blocking", BlockingHandler(started, release))
        worker = Worker(factory, registry, heartbeat_interval_seconds=0.01)
        thread = Thread(target=worker.run_once)
        thread.start()
        assert started.wait(timeout=2)
        sleep(0.05)
        with factory() as check_session:
            running = check_session.get(Job, job.id)
            assert running is not None and running.status is JobStatus.running
            assert running.heartbeat_at is not None and running.heartbeat_at > running.created_at
        release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
    engine.dispose()


def test_stale_running_job_recovers_without_overwriting_new_claim(db_session, owner):
    job = enqueue(db_session, "result", Payload(value="stale"), owner.id, "stale")
    db_session.commit()
    claimed = claim_next_job(db_session, "worker-a")
    assert claimed is not None
    claimed.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    db_session.commit()

    assert recover_stale_jobs(db_session, datetime.now(UTC), stale_after_seconds=60, max_attempts=3) == 1
    db_session.commit()
    db_session.refresh(job)
    assert job.status is JobStatus.retrying
    assert job.claim_token is None

    job.status = JobStatus.running
    job.claim_token = "new-claim"
    job.heartbeat_at = datetime.now(UTC)
    db_session.commit()
    assert recover_stale_jobs(db_session, datetime.now(UTC), stale_after_seconds=60, max_attempts=3) == 0
    db_session.refresh(job)
    assert job.claim_token == "new-claim"


def test_api_hides_jobs_owned_by_other_users(db_session, owner):
    outsider = User(username="jobs-outsider", password_hash=hash_password("correct"))
    db_session.add(outsider)
    job = enqueue(db_session, "result", Payload(value="private"), owner.id, "private")
    db_session.commit()
    app = create_app(Settings(environment="test", database_url="sqlite://", jwt_secret="test-secret-at-least-thirty-two-bytes"))

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        token = client.post("/api/auth/login", data={"username": outsider.username, "password": "correct"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(f"/api/jobs/{job.id}", headers=headers).status_code == 404
        assert client.post(f"/api/jobs/{job.id}/cancel", headers=headers).status_code == 404
