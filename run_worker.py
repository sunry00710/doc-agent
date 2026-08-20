from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.jobs.runner import JobRegistry, Worker


def build_registry() -> JobRegistry:
    """Application extension point for registering production job handlers."""
    return JobRegistry()


def create_worker(engine, registry: JobRegistry | None = None) -> Worker:
    registry = registry or build_registry()
    if not registry.handlers:
        raise RuntimeError("no registered handlers")
    settings = Settings()
    return Worker(
        create_session_factory(engine),
        registry,
        max_attempts=settings.job_max_attempts,
        heartbeat_interval_seconds=settings.job_heartbeat_seconds,
        stale_after_seconds=settings.job_stale_after_seconds,
    )


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        worker = create_worker(engine)
        worker.run_forever(settings.job_poll_interval_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
