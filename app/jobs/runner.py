from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.jobs.service import (
    RetryableJobError,
    claim_next_job,
    fail_job,
    finish_job,
    heartbeat,
    recover_stale_jobs,
    utc_now,
)


class JobHandler(ABC):
    """Handlers are at-least-once; use _job_context fencing for external side effects."""

    @abstractmethod
    def run(self, payload: dict) -> dict: ...


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        if not job_type or job_type in self._handlers:
            raise ValueError("Job handler registration is invalid")
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)

    @property
    def handlers(self) -> dict[str, JobHandler]:
        return self._handlers.copy()


class Worker:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        registry: JobRegistry,
        *,
        worker_id: str = "worker",
        max_attempts: int = 3,
        retry_delay_seconds: int = 30,
        heartbeat_interval_seconds: float = 30,
        stale_after_seconds: int = 120,
        sqlite_lock_retries: int = 3,
        sqlite_lock_backoff_seconds: float = 0.05,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if isinstance(session_factory, Session) or not callable(session_factory):
            raise TypeError("Worker requires a session factory for heartbeat safety")
        self.session_factory = session_factory
        self.registry = registry
        self.worker_id = worker_id
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.sqlite_lock_retries = sqlite_lock_retries
        self.sqlite_lock_backoff_seconds = sqlite_lock_backoff_seconds
        self.clock = clock

    def run_once(self) -> bool:
        for attempt in range(self.sqlite_lock_retries + 1):
            try:
                with self.session_factory() as session:
                    return self._run_once(session)
            except OperationalError as exc:
                if not _is_sqlite_lock_error(exc) or attempt == self.sqlite_lock_retries:
                    raise
                time.sleep(self.sqlite_lock_backoff_seconds * (2**attempt))
        raise AssertionError("unreachable")

    def _run_once(self, session: Session) -> bool:
        now = self.clock()
        recover_stale_jobs(session, now, stale_after_seconds=self.stale_after_seconds, max_attempts=self.max_attempts)
        session.commit()
        job = claim_next_job(session, self.worker_id, now)
        if job is None:
            session.rollback()
            return False
        session.commit()
        handler = self.registry.get(job.job_type)
        if handler is None:
            fail_job(session, job, retryable=False, max_attempts=self.max_attempts, retry_delay_seconds=0, now=self.clock())
        else:
            claim_token = job.claim_token
            if claim_token is None:
                raise RuntimeError("claimed job is missing its claim token")
            payload = {
                **job.payload,
                "_job_context": {
                    "job_id": job.id,
                    "idempotency_key": job.idempotency_key,
                    "attempt": job.attempts,
                    "claim_token": claim_token,
                },
            }
            stop_heartbeat = Event()
            heartbeat_thread = self._start_heartbeat(job.id, claim_token, stop_heartbeat)
            try:
                result = handler.run(payload)
            except RetryableJobError:
                fail_result = (True, self.retry_delay_seconds)
            except Exception:  # noqa: BLE001 - worker converts handler failures to safe job state
                fail_result = (False, 0)
            else:
                fail_result = None
            finally:
                stop_heartbeat.set()
                heartbeat_thread.join()
            if fail_result is None:
                finish_job(session, job.id, claim_token, result, now=self.clock())
            else:
                fail_job(session, job, retryable=fail_result[0], max_attempts=self.max_attempts, retry_delay_seconds=fail_result[1], now=self.clock())
        session.commit()
        return True

    def _start_heartbeat(self, job_id: str, claim_token: str, stop: Event) -> Thread:
        def renew() -> None:
            while not stop.wait(self.heartbeat_interval_seconds):
                try:
                    with self.session_factory() as heartbeat_session:
                        heartbeat(heartbeat_session, job_id, claim_token, now=self.clock())
                        heartbeat_session.commit()
                except OperationalError as exc:
                    if not _is_sqlite_lock_error(exc):
                        raise

        thread = Thread(target=renew, name=f"job-heartbeat-{job_id}", daemon=True)
        thread.start()
        return thread

    def run_forever(self, poll_interval_seconds: float, sleeper: Callable[[float], None] = time.sleep) -> None:
        while True:
            try:
                ran_job = self.run_once()
            except OperationalError as exc:
                if not _is_sqlite_lock_error(exc):
                    raise
                ran_job = False
            if not ran_job:
                sleeper(poll_interval_seconds)


def _is_sqlite_lock_error(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower() or "database is busy" in str(exc).lower()
