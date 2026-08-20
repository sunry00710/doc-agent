from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.jobs.runner import JobRegistry, Worker


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        worker = Worker(
            create_session_factory(engine),
            JobRegistry(),
            max_attempts=settings.job_max_attempts,
            heartbeat_interval_seconds=settings.job_heartbeat_seconds,
            stale_after_seconds=settings.job_stale_after_seconds,
        )
        worker.run_forever(settings.job_poll_interval_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
