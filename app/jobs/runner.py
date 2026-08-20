from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread

from sqlalchemy.orm import Session, sessionmaker

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


class Worker:
    def __init__(self, session_or_factory: Session | sessionmaker[Session], registry: JobRegistry, *, worker_id: str = "worker", max_attempts: int = 3, retry_delay_seconds: int = 30, heartbeat_interval_seconds: float = 30, stale_after_seconds: int = 120, clock: Callable[[], datetime] = utc_now) -> None:
        self.session_or_factory = session_or_factory
        self.registry = registry
        self.worker_id = worker_id
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.clock = clock

    def run_once(self) -> bool:
        if isinstance(self.session_or_factory, Session):
            return self._run_once(self.session_or_factory)
        with self.session_or_factory() as session:
            return self._run_once(session)

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
            stop_heartbeat = Event()
            heartbeat_thread = self._start_heartbeat(job.id, job.claim_token or "", stop_heartbeat)
            try:
                result = handler.run(job.payload)
            except RetryableJobError:
                fail_job(session, job, retryable=True, max_attempts=self.max_attempts, retry_delay_seconds=self.retry_delay_seconds, now=self.clock())
            except Exception:  # noqa: BLE001 - worker converts handler failures to safe job state
                fail_job(session, job, retryable=False, max_attempts=self.max_attempts, retry_delay_seconds=0, now=self.clock())
            else:
                finish_job(session, job.id, job.claim_token or "", result, now=self.clock())
            finally:
                stop_heartbeat.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join()
        session.commit()
        return True

    def _start_heartbeat(self, job_id: str, claim_token: str, stop: Event) -> Thread | None:
        if isinstance(self.session_or_factory, Session):
            return None

        def renew() -> None:
            while not stop.wait(self.heartbeat_interval_seconds):
                with self.session_or_factory() as heartbeat_session:
                    heartbeat(heartbeat_session, job_id, claim_token, now=self.clock())
                    heartbeat_session.commit()

        thread = Thread(target=renew, name=f"job-heartbeat-{job_id}", daemon=True)
        thread.start()
        return thread

    def run_forever(self, poll_interval_seconds: float, sleeper: Callable[[float], None] = time.sleep) -> None:
        while True:
            if not self.run_once():
                sleeper(poll_interval_seconds)
