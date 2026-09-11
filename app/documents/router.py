from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.documents.models import Document
from app.documents.schemas import DocumentCreate, DocumentRead, DocumentVersionRead
from app.documents.service import (
    create_document,
    create_version,
    list_documents,
    list_versions,
    read_document,
    read_version,
)
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.knowledge.ingestion_queue import enqueue_ingestion

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_storage(request: Request) -> FileStorage:
    return FileStorage(request.app.state.settings)


def read_upload_content(file_object: object, max_upload_bytes: int) -> bytes:
    content = file_object.read(max_upload_bytes + 1)
    if len(content) > max_upload_bytes:
        raise ValueError("Document is too large")
    return content


@router.get("", response_model=list[DocumentRead])
def list_for_project(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    return list_documents(session, project_id, current_user)


@router.get("/{document_id}", response_model=DocumentRead)
def read(
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    return read_document(session, document_id, current_user)


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create(
    data: DocumentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    document = create_document(
        session, data.project_id, data.title, data.domain, data.document_type, current_user
    )
    session.commit()
    return document


@router.post(
    "/{document_id}/versions", response_model=DocumentVersionRead, status_code=status.HTTP_201_CREATED
)
def upload(
    document_id: UUID,
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
):
    try:
        content = read_upload_content(file.file, storage.max_upload_bytes)
        version = create_version(session, storage, document_id, content, current_user, file.filename)
        # 与版本同一事务入队：提交失败则 Job 一并回滚，不会留下指向不存在版本的索引任务
        document = session.get(Document, version.document_id)
        if document is not None:
            enqueue_ingestion(session, version.id, document.project_id, current_user)
    except ValueError as exc:
        raise AppError("validation_error", "Invalid document upload", 422) from exc
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return version


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
def list_for_document(
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    return list_versions(session, document_id, current_user)


@router.get("/{document_id}/versions/{number}")
def read_content(
    document_id: UUID,
    number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
):
    content = read_version(session, storage, document_id, number, current_user)
    return Response(content=content, media_type="text/plain; charset=utf-8")
