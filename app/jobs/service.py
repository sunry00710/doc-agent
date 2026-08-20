from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.jobs.models import Job, JobStatus


class RetryableJobError(Exception):
    """A handler may raise this to request a configured retry."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def enqueue(session: Session, job_type: str, payload: BaseModel, owner_id: UUID | str, idempotency_key: str) -> Job:
    """Create or return a job scoped by (owner_id, job_type, idempotency_key)."""
    if not isinstance(payload, BaseModel):
        raise TypeError("job payload must be a Pydantic BaseModel")
    if (
        "_job_context" in type(payload).__private_attributes__
        or any(
            field_name == "_job_context" or field.alias == "_job_context"
            for field_name, field in type(payload).model_fields.items()
        )
    ):
        raise ValueError("_job_context is reserved for worker metadata")

    owner = str(owner_id)
    existing = _idempotent_job(session, owner, job_type, idempotency_key)
    if existing is not None:
        return existing
    job = Job(job_type=job_type, payload=payload.model_dump(mode="json"), owner_id=owner, idempotency_key=idempotency_key, next_attempt_at=utc_now())
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        existing = _idempotent_job(session, owner, job_type, idempotency_key)
        if existing is not None:
            return existing
        raise
    return job


def _idempotent_job(session: Session, owner_id: str, job_type: str, key: str) -> Job | None:
    return session.scalar(select(Job).where(Job.owner_id == owner_id, Job.job_type == job_type, Job.idempotency_key == key))


def claim_next_job(session: Session, worker_id: str, now: datetime | None = None) -> Job | None:
    now = now or utc_now()
    claim_token = str(uuid4())
    claimable = and_(Job.status.in_((JobStatus.queued, JobStatus.retrying)), or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now))
    query = select(Job).where(claimable).order_by(Job.created_at, Job.id).limit(1)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    candidate = session.scalar(query)
    if candidate is None:
        return None
    updated = session.scalar(update(Job).where(Job.id == candidate.id, claimable).values(status=JobStatus.running, attempts=Job.attempts + 1, claim_token=claim_token, worker_id=worker_id, heartbeat_at=now, updated_at=now).returning(Job), execution_options={"synchronize_session": False})
    if updated is not None:
        session.refresh(updated)
    return updated


def heartbeat(session: Session, job_id: str, claim_token: str, now: datetime | None = None) -> bool:
    result = session.execute(update(Job).where(Job.id == job_id, Job.status == JobStatus.running, Job.claim_token == claim_token).values(heartbeat_at=now or utc_now(), updated_at=now or utc_now()))
    return result.rowcount == 1


def finish_job(session: Session, job_id: str, claim_token: str, result: dict, now: datetime | None = None) -> bool:
    updated = session.execute(update(Job).where(Job.id == job_id, Job.status == JobStatus.running, Job.claim_token == claim_token).values(status=JobStatus.succeeded, result=result, error=None, claim_token=None, worker_id=None, heartbeat_at=None, next_attempt_at=None, updated_at=now or utc_now()))
    return updated.rowcount == 1


def fail_job(session: Session, job: Job, *, retryable: bool, max_attempts: int, retry_delay_seconds: int, now: datetime | None = None) -> bool:
    now = now or utc_now()
    should_retry = retryable and job.attempts < max_attempts
    updated = session.execute(update(Job).where(Job.id == job.id, Job.status == JobStatus.running, Job.claim_token == job.claim_token).values(status=JobStatus.retrying if should_retry else JobStatus.failed, error={"code": "retryable_failure" if retryable else "job_failed", "message": "Job execution failed"}, claim_token=None, worker_id=None, heartbeat_at=None, next_attempt_at=now + timedelta(seconds=retry_delay_seconds) if should_retry else None, updated_at=now))
    return updated.rowcount == 1


def cancel_job(session: Session, job_id: str, owner_id: UUID | str) -> bool:
    updated = session.execute(update(Job).where(Job.id == str(job_id), Job.owner_id == str(owner_id), Job.status.in_((JobStatus.queued, JobStatus.retrying))).values(status=JobStatus.cancelled, next_attempt_at=None, updated_at=utc_now()))
    return updated.rowcount == 1


def retry_job(session: Session, job_id: str, owner_id: UUID | str) -> bool:
    updated = session.execute(update(Job).where(Job.id == str(job_id), Job.owner_id == str(owner_id), Job.status.in_((JobStatus.failed, JobStatus.cancelled))).values(status=JobStatus.queued, error=None, result=None, next_attempt_at=utc_now(), updated_at=utc_now()))
    return updated.rowcount == 1


def recover_stale_jobs(session: Session, now: datetime, *, stale_after_seconds: int, max_attempts: int) -> int:
    stale_before = now - timedelta(seconds=stale_after_seconds)
    stale = list(session.scalars(select(Job).where(Job.status == JobStatus.running, Job.heartbeat_at < stale_before)))
    recovered = 0
    for job in stale:
        should_retry = job.attempts < max_attempts
        updated = session.execute(update(Job).where(Job.id == job.id, Job.status == JobStatus.running, Job.claim_token == job.claim_token, Job.heartbeat_at < stale_before).values(status=JobStatus.retrying if should_retry else JobStatus.failed, error={"code": "stale_worker", "message": "Job execution interrupted"}, claim_token=None, worker_id=None, heartbeat_at=None, next_attempt_at=now if should_retry else None, updated_at=now))
        recovered += updated.rowcount
    return recovered


def get_owned_job(session: Session, job_id: UUID | str, owner_id: UUID | str) -> Job | None:
    return session.scalar(select(Job).where(Job.id == str(job_id), Job.owner_id == str(owner_id)))


def list_owned_jobs(session: Session, owner_id: UUID | str) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.owner_id == str(owner_id)).order_by(Job.created_at.desc())))
