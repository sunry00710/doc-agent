from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import DocumentVersion
from app.documents.storage import FileStorage
from app.knowledge.chunking import chunk_markdown
from app.knowledge.models import (
    GenerationState,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeSpace,
    KnowledgeState,
)

_SQLITE_RETRY_ATTEMPTS = 5
_SQLITE_RETRY_DELAY_SECONDS = 0.01


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


def ingest_version(session: Session, storage: FileStorage, version_id: UUID, space_id: UUID, *, rebuild: bool = False) -> KnowledgeDocument:
    def index() -> KnowledgeDocument:
        version = session.get(DocumentVersion, str(version_id))
        space = session.get(KnowledgeSpace, str(space_id))
        if version is None or space is None:
            raise AppError("not_found", "Knowledge source not found", 404)
        source = _read_verified_source(storage, version)
        document = _active_document(session, version.id, space.id)
        if document is not None and not rebuild:
            return document
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
                if active is not None and not rebuild:
                    return active
                generation = KnowledgeGeneration(knowledge_document_id=document.id, state=GenerationState.building)
                session.add(generation)
                session.flush()
                for chunk in chunk_markdown(source, version.id):
                    session.add(KnowledgeChunk(id=chunk.id, generation_id=generation.id, version_id=version.id, heading_path=list(chunk.heading_path), start_offset=chunk.start_offset, end_offset=chunk.end_offset, text=chunk.text))
                    session.execute(text("INSERT INTO knowledge_chunks_fts (chunk_id, generation_id, text) VALUES (:chunk_id, :generation_id, :text)"), {"chunk_id": chunk.id, "generation_id": generation.id, "text": _fts_text(chunk.text)})
                session.flush()
                document.active_generation_id = generation.id
                generation.state = GenerationState.active
                session.flush()
        except OperationalError:
            raise
        except (SQLAlchemyError, OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
            raise _index_failure(exc) from exc
        return document

    try:
        return _retry_sqlite_busy(index)
    except OperationalError as exc:
        raise _index_failure(exc) from exc
