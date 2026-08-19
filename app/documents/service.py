from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.projects.permissions import ProjectAction, require_project_permission

MAX_VERSION_ATTEMPTS = 3


def create_document(
    session: Session,
    project_id: UUID,
    title: str,
    domain: str,
    document_type: str,
    actor: User,
) -> Document:
    require_project_permission(project_id, ProjectAction.edit, actor, session)
    document = Document(
        project_id=str(project_id),
        owner_id=actor.id,
        title=title.strip(),
        domain=domain.strip(),
        document_type=document_type.strip(),
    )
    session.add(document)
    session.flush()
    return document


def create_version(
    session: Session,
    storage: FileStorage,
    document_id: UUID,
    content: bytes,
    actor: User,
    filename: str = "content.txt",
) -> DocumentVersion:
    """Create an immutable version; the caller owns the surrounding transaction.

    Exact signature: ``create_version(session, storage, document_id, content, actor,
    filename='content.txt') -> DocumentVersion``.
    """
    document = _require_document_permission(session, document_id, actor, ProjectAction.edit)
    stored = storage.store(filename, content)
    try:
        for _attempt in range(MAX_VERSION_ATTEMPTS):
            version = DocumentVersion(
                document_id=document.id,
                number=_next_version_number(session, document.id),
                content_sha256=stored.content_sha256,
                storage_key=stored.storage_key,
                created_by=actor.id,
            )
            try:
                with session.begin_nested():
                    session.add(version)
                    session.flush()
                return version
            except IntegrityError as exc:
                if not _is_version_number_conflict(exc):
                    raise
        raise AppError("conflict", "Unable to create document version", 409, retryable=True)
    except Exception:
        storage.delete(stored.storage_key)
        raise


def list_versions(session: Session, document_id: UUID, actor: User) -> list[DocumentVersion]:
    document = _require_document_permission(session, document_id, actor, ProjectAction.view)
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        )
    )


def read_version(
    session: Session, storage: FileStorage, document_id: UUID, number: int, actor: User
) -> bytes:
    document = _require_document_permission(session, document_id, actor, ProjectAction.view)
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.number == number
        )
    )
    if version is None:
        raise AppError("not_found", "Document version not found", 404)
    try:
        return storage.read(version.storage_key)
    except (OSError, ValueError) as exc:
        raise AppError("not_found", "Document version not found", 404) from exc


def _require_document_permission(
    session: Session, document_id: UUID, actor: User, action: ProjectAction
) -> Document:
    document = session.get(Document, str(document_id))
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(UUID(document.project_id), action, actor, session)
    return document


def _next_version_number(session: Session, document_id: str) -> int:
    current = session.scalar(
        select(func.max(DocumentVersion.number)).where(DocumentVersion.document_id == document_id)
    )
    return (current or 0) + 1


def _is_version_number_conflict(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return "document_versions.document_id, document_versions.number" in message or (
        "uq_document_versions_document_number" in message
    )
