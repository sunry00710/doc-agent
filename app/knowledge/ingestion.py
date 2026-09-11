from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from threading import Lock, RLock
from uuid import UUID

from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import DocumentVersion
from app.documents.storage import FileStorage
from app.jobs.models import Job, JobStatus
from app.jobs.runner import JobHandler
from app.jobs.service import RetryableJobError
from app.knowledge.chunking import chunk_markdown
from app.knowledge.embeddings import EmbeddingProvider, normalized_documents
from app.knowledge.models import (
    GenerationState,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeGeneration,
    KnowledgeSpace,
    KnowledgeState,
)
from app.knowledge.schemas import IngestionJobPayload

_SQLITE_RETRY_ATTEMPTS = 5
_SQLITE_RETRY_DELAY_SECONDS = 0.01
_INGESTION_LOCKS_GUARD = Lock()
_INGESTION_LOCKS: dict[tuple[str, str], tuple[RLock, int]] = {}


def _acquire_ingestion_lock(
    version_id: UUID,
    space_id: UUID,
) -> tuple[tuple[str, str], RLock]:
    key = (str(version_id), str(space_id))
    with _INGESTION_LOCKS_GUARD:
        lock, users = _INGESTION_LOCKS.get(key, (RLock(), 0))
        _INGESTION_LOCKS[key] = (lock, users + 1)
    lock.acquire()
    return key, lock


def _release_ingestion_lock(
    session: Session,
    key: tuple[str, str],
    lock: RLock,
) -> None:
    def release() -> None:
        lock.release()
        with _INGESTION_LOCKS_GUARD:
            current_lock, users = _INGESTION_LOCKS[key]
            if users == 1:
                del _INGESTION_LOCKS[key]
            else:
                _INGESTION_LOCKS[key] = (
                    current_lock,
                    users - 1,
                )

    if session.in_transaction():
        pending = session.info.setdefault("ingestion_lock_releases", [])
        pending.append(release)
        if not session.info.get("ingestion_lock_listener_registered"):
            def on_transaction_end(_session: Session, transaction: object) -> None:
                if getattr(transaction, "parent", None) is not None:
                    return
                callbacks = session.info.pop("ingestion_lock_releases", [])
                session.info["ingestion_lock_listener_registered"] = False
                for callback in callbacks:
                    callback()

            event.listen(session, "after_transaction_end", on_transaction_end)
            session.info["ingestion_lock_listener_registered"] = True
    else:
        release()


def _is_sqlite_busy(exc: OperationalError) -> bool:
    message = str(exc.orig).lower()
    return not exc.connection_invalidated and ("database is locked" in message or "database is busy" in message)


def _retry_sqlite_busy[T](operation: Callable[[], T]) -> T:
    for attempt in range(_SQLITE_RETRY_ATTEMPTS):
        try:
            return operation()
        except OperationalError as exc:
            if not _is_sqlite_busy(exc) or attempt == _SQLITE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_SQLITE_RETRY_DELAY_SECONDS * (attempt + 1))
    raise AssertionError("unreachable")


def _active_document(session: Session, version_id: str, space_id: str) -> KnowledgeDocument | None:
    document = session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.version_id == version_id, KnowledgeDocument.space_id == space_id))
    if document is None or document.active_generation_id is None:
        return None
    generation = session.get(KnowledgeGeneration, document.active_generation_id)
    return document if generation is not None and generation.state == GenerationState.active else None


def _fts_text(source: str) -> str:
    return "".join(f" {character} " if "一" <= character <= "鿿" else character for character in source)


def _indexed_text(chunk: object) -> str:
    # 标题路径参与 FTS 索引：保证按章节标题（如“责任分工”）检索可命中正文块
    heading_path = getattr(chunk, "heading_path", None) or []
    body = getattr(chunk, "text", "")
    return " ".join([*heading_path, body])


def _index_failure(exc: Exception | None = None) -> AppError:
    error = AppError("index_failure", "Knowledge index verification failed", 500)
    if exc is not None:
        error.__cause__ = exc
    return error


def _read_verified_source(storage: FileStorage, version: DocumentVersion) -> str:
    try:
        content = storage.read(version.storage_key)
        if hashlib.sha256(content).hexdigest() != version.content_sha256:
            raise _index_failure()
        return content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except AppError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _index_failure(exc) from exc


def _has_complete_embeddings(session: Session, generation_id: str) -> bool:
    chunk_count = session.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.generation_id == generation_id))
    embedding_count = session.scalar(select(func.count()).select_from(KnowledgeEmbedding).where(KnowledgeEmbedding.generation_id == generation_id))
    return chunk_count == embedding_count


def ingest_version(
    session: Session,
    storage: FileStorage,
    version_id: UUID,
    space_id: UUID,
    *,
    rebuild: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
) -> KnowledgeDocument:
    if session.bind is None or session.bind.dialect.name != "sqlite":
        raise _index_failure()

    def index() -> KnowledgeDocument:
        should_rebuild = rebuild
        version = session.get(DocumentVersion, str(version_id))
        space = session.get(KnowledgeSpace, str(space_id))
        if version is None or space is None:
            raise AppError("not_found", "Knowledge source not found", 404)
        source = _read_verified_source(storage, version)
        document = _active_document(session, version.id, space.id)
        if document is not None and not should_rebuild:
            if embedding_provider is None or _has_complete_embeddings(session, document.active_generation_id):
                return document
            should_rebuild = True
        if document is None:
            try:
                with session.begin_nested():
                    document = KnowledgeDocument(version_id=version.id, space_id=space.id, state=KnowledgeState.indexed)
                    session.add(document)
                    session.flush()
            except IntegrityError:
                document = session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.version_id == version.id, KnowledgeDocument.space_id == space.id))
                if document is None:
                    raise
        assert document is not None

        try:
            with session.begin_nested():
                active = _active_document(session, version.id, space.id)
                if active is not None and not should_rebuild:
                    if embedding_provider is None or _has_complete_embeddings(session, active.active_generation_id):
                        return active
                    should_rebuild = True
                generation = KnowledgeGeneration(knowledge_document_id=document.id, state=GenerationState.building)
                session.add(generation)
                session.flush()
                chunks = chunk_markdown(source, version.id)
                vectors = normalized_documents(embedding_provider, [chunk.text for chunk in chunks]) if embedding_provider is not None and chunks else None
                for index, chunk in enumerate(chunks):
                    session.add(KnowledgeChunk(id=chunk.id, generation_id=generation.id, version_id=version.id, heading_path=list(chunk.heading_path), start_offset=chunk.start_offset, end_offset=chunk.end_offset, text=chunk.text))
                    session.execute(text("INSERT INTO knowledge_chunks_fts (chunk_id, generation_id, text) VALUES (:chunk_id, :generation_id, :text)"), {"chunk_id": chunk.id, "generation_id": generation.id, "text": _fts_text(_indexed_text(chunk))})
                    if vectors is not None:
                        session.add(KnowledgeEmbedding(chunk_id=chunk.id, generation_id=generation.id, dimension=int(vectors.shape[1]), vector=vectors[index].tobytes()))
                session.flush()
                document.active_generation_id = generation.id
                generation.state = GenerationState.active
                session.flush()
        except OperationalError:
            raise
        except (SQLAlchemyError, OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
            raise _index_failure(exc) from exc
        return document

    lock_key, lock = _acquire_ingestion_lock(
        version_id,
        space_id,
    )
    try:
        return _retry_sqlite_busy(index)
    except OperationalError as exc:
        raise _index_failure(exc) from exc
    finally:
        _release_ingestion_lock(
            session,
            lock_key,
            lock,
        )


class JobClaimLostError(Exception):
    """The worker no longer owns the job claim needed for ingestion."""


class KnowledgeIngestionHandler(JobHandler):
    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: FileStorage | None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.embedding_provider = embedding_provider

    def run(self, payload: dict) -> dict:
        payload = payload.copy()
        context = payload.pop("_job_context", None)
        if set(context or ()) != {"job_id", "idempotency_key", "attempt", "claim_token"}:
            raise ValueError("_job_context is missing or invalid")
        if not all(isinstance(context[field], str) for field in ("job_id", "idempotency_key", "claim_token")) or not isinstance(context["attempt"], int):
            raise ValueError("_job_context is missing or invalid")
        job_payload = IngestionJobPayload.model_validate(payload)
        if self.storage is None:
            raise RetryableJobError("knowledge storage is unavailable")
        try:
            with self.session_factory() as session:
                fence = session.execute(
                    update(Job)
                    .where(
                        Job.id == context["job_id"],
                        Job.claim_token == context["claim_token"],
                        Job.status == JobStatus.running,
                    )
                    .values(updated_at=Job.updated_at)
                )
                if fence.rowcount != 1:
                    session.rollback()
                    raise JobClaimLostError("knowledge ingestion claim is no longer active")
                ingest_kwargs = {"embedding_provider": self.embedding_provider} if self.embedding_provider is not None else {}
                document = ingest_version(
                    session,
                    self.storage,
                    job_payload.version_id,
                    job_payload.space_id,
                    **ingest_kwargs,
                )
                session.commit()
                return {
                    "version_id": str(job_payload.version_id),
                    "space_id": str(job_payload.space_id),
                    "generation_id": document.active_generation_id,
                    "job_id": context["job_id"],
                    "idempotency_key": context["idempotency_key"],
                    "attempt": context["attempt"],
                }
        except AppError as exc:
            if exc.code == "index_failure":
                raise RetryableJobError("knowledge indexing is unavailable") from exc
            raise
