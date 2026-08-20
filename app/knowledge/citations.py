from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.knowledge.models import KnowledgeChunk
from app.knowledge.schemas import Citation


def assemble_citation(session: Session, storage: FileStorage, chunk_id: str, generation_id: str | None = None) -> Citation:
    statement = select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
    if generation_id is not None:
        statement = statement.where(KnowledgeChunk.generation_id == generation_id)
    chunk = session.scalar(statement)
    if chunk is None:
        raise AppError("not_found", "Knowledge chunk not found", 404)
    version = session.get(DocumentVersion, chunk.version_id)
    document = session.get(Document, version.document_id) if version is not None else None
    if version is None or document is None:
        raise AppError("index_failure", "Knowledge index verification failed", 500)
    try:
        source = storage.read(version.storage_key)
        if hashlib.sha256(source).hexdigest() != version.content_sha256:
            raise AppError("index_failure", "Knowledge index verification failed", 500)
        text = source.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except AppError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AppError("index_failure", "Knowledge index verification failed", 500) from exc
    quote = text[chunk.start_offset : chunk.end_offset]
    if quote != chunk.text or len(quote) != chunk.end_offset - chunk.start_offset:
        raise AppError("index_failure", "Knowledge index verification failed", 500)
    return Citation(chunk_id=chunk.id, document_id=UUID(document.id), version_id=UUID(version.id), title=document.title, heading_path=tuple(chunk.heading_path), quote=quote, start_offset=chunk.start_offset, end_offset=chunk.end_offset)
