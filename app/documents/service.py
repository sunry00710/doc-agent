from __future__ import annotations

from uuid import UUID

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.projects.permissions import ProjectAction, require_project_permission

_PENDING_DOCUMENT_FILES = "pending_document_files"


@event.listens_for(Session, "after_commit")
def retain_committed_document_files(session: Session) -> None:
    """Promote committed savepoint files or discard outer-commit cleanup state."""
    pending_by_transaction = session.info.get(_PENDING_DOCUMENT_FILES)
    if pending_by_transaction is None:
        return

    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None or transaction.parent is None:
        session.info.pop(_PENDING_DOCUMENT_FILES, None)
        return

    pending = pending_by_transaction.pop(transaction, [])
    if pending:
        pending_by_transaction.setdefault(transaction.parent, []).extend(pending)
    if not pending_by_transaction:
        session.info.pop(_PENDING_DOCUMENT_FILES, None)


@event.listens_for(Session, "after_soft_rollback")
def remove_rolled_back_document_files(session: Session, transaction) -> None:
    """Compensate only files registered in the transaction that rolled back."""
    pending_by_transaction = session.info.get(_PENDING_DOCUMENT_FILES)
    if pending_by_transaction is None:
        return

    pending = pending_by_transaction.pop(transaction, [])
    for storage, storage_key in pending:
        storage.delete(storage_key)
    if not pending_by_transaction:
        session.info.pop(_PENDING_DOCUMENT_FILES, None)


def _register_file_cleanup(session: Session, storage: FileStorage, storage_key: str) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        raise RuntimeError("Document version file must be registered within a transaction")
    session.info.setdefault(_PENDING_DOCUMENT_FILES, {}).setdefault(transaction, []).append(
        (storage, storage_key)
    )


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
        number = _allocate_version_number(session, document.id)
        version = DocumentVersion(
            document_id=document.id,
            number=number,
            content_sha256=stored.content_sha256,
            storage_key=stored.storage_key,
            created_by=actor.id,
        )
        session.add(version)
        session.flush()
        _register_file_cleanup(session, storage, stored.storage_key)
        return version
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


def _allocate_version_number(session: Session, document_id: str) -> int:
    allocated = session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(next_version_number=Document.next_version_number + 1)
        .returning(Document.next_version_number)
    ).scalar_one()
    return allocated - 1
