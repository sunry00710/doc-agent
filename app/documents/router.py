from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.documents.schemas import DocumentCreate, DocumentRead, DocumentVersionRead
from app.documents.service import (
    create_document,
    create_version,
    list_versions,
    read_version,
)
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_storage(request: Request) -> FileStorage:
    return FileStorage(request.app.state.settings)


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
        content = file.file.read()
        version = create_version(session, storage, document_id, content, current_user, file.filename)
    except ValueError as exc:
        raise AppError("validation_error", "Invalid document upload", 422) from exc
    session.commit()
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
