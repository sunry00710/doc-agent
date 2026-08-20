from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.documents.storage import FileStorage
from app.jobs.runner import JobRegistry, Worker
from app.knowledge.ingestion import KnowledgeIngestionHandler


def build_registry(session_factory=None, storage: FileStorage | None = None) -> JobRegistry:
    """Register production handlers with their isolated dependencies."""
    registry = JobRegistry()
    if session_factory is not None:
        registry.register("knowledge.ingest", KnowledgeIngestionHandler(session_factory, storage))
    return registry


def create_worker(engine, registry: JobRegistry | None = None) -> Worker:
    settings = Settings()
    session_factory = create_session_factory(engine)
    registry = registry or build_registry(session_factory, FileStorage(settings))
    if not registry.handlers:
        raise RuntimeError("no registered handlers")
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
