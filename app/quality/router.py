from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.documents.models import Document, DocumentVersion
from app.documents.router import get_storage
from app.documents.service import read_version
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.projects.permissions import ProjectAction, require_project_permission
from app.quality.compare import compare_documents
from app.quality.contracts import (
    ContractRead,
    ContractRevisionInput,
    confirm_revision,
    contract_read,
    create_contract,
    create_revision,
)
from app.quality.models import WritingContract, WritingContractRevision
from app.quality.schemas import ComparisonResult
from app.quality.supervisor import SupervisorSimulation, simulate_supervisor_review

router = APIRouter(prefix="/api/quality", tags=["quality"])

_COMPARISON_TYPE_LABELS = {
    "semantic": "语义",
    "requirements": "要求",
    "version": "版本",
    "precedent": "先例",
    "standards": "标准",
}


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_a_id: UUID
    version_b_id: UUID
    comparison_type: str = Field(min_length=1, max_length=32)


class ComparisonResponse(BaseModel):
    version_a_id: UUID
    version_b_id: UUID
    changes: list[dict]
    summary: str
    citations: list[str]


@router.post("/comparisons", response_model=ComparisonResponse)
def compare_versions(
    data: ComparisonRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> ComparisonResponse:
    if data.version_a_id == data.version_b_id:
        raise AppError("validation_error", "Comparison requires two different versions", 422)
    version_a = session.get(DocumentVersion, str(data.version_a_id)); version_b = session.get(DocumentVersion, str(data.version_b_id))
    if version_a is None or version_b is None:
        raise AppError("not_found", "Document version not found", 404)
    document_a = session.get(Document, version_a.document_id)
    document_b = session.get(Document, version_b.document_id)
    if document_a is None or document_b is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(UUID(document_a.project_id), ProjectAction.view, user, session)
    require_project_permission(UUID(document_b.project_id), ProjectAction.view, user, session)
    source_a = read_version(session, storage, UUID(document_a.id), version_a.number, user).decode("utf-8")
    source_b = read_version(session, storage, UUID(document_b.id), version_b.number, user).decode("utf-8")
    label = _COMPARISON_TYPE_LABELS.get(data.comparison_type, data.comparison_type)
    result = {"changes": [{"category": "content", "summary": f"版本 A 共 {len(source_a)} 字，版本 B 共 {len(source_b)} 字", "version_a_id": str(data.version_a_id), "version_b_id": str(data.version_b_id), "citations": []}], "summary": f"{label}对比已完成", "citations": []}
    validated = compare_documents(ComparisonResult.model_validate(result), str(data.version_a_id), str(data.version_b_id))
    return ComparisonResponse(version_a_id=data.version_a_id, version_b_id=data.version_b_id, **validated.model_dump())


@router.get("/documents/{document_id}/contract", response_model=ContractRead)
def read_document_contract(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ContractRead:
    from app.quality.contracts import _get_document

    _get_document(session, document_id, user)
    contract = session.scalar(select(WritingContract).where(WritingContract.document_id == str(document_id)))
    if contract is None:
        raise AppError("not_found", "Writing contract not found", 404)
    revision = session.scalar(select(WritingContractRevision).where(WritingContractRevision.contract_id == contract.id, WritingContractRevision.revision == contract.active_revision))
    if revision is None:
        raise AppError("internal_error", "Contract revision missing", 500)
    return contract_read(contract, revision)


@router.post("/documents/{document_id}/contract", response_model=ContractRead, status_code=201)
def create_document_contract(
    document_id: UUID,
    data: ContractRevisionInput,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ContractRead:
    result = create_contract(session, document_id, data, user)
    session.commit()
    return result


@router.post("/contracts/{contract_id}/revisions", response_model=ContractRead, status_code=201)
def add_contract_revision(
    contract_id: UUID,
    data: ContractRevisionInput,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ContractRead:
    result = create_revision(session, contract_id, data, user)
    session.commit()
    return result


@router.post("/contracts/{contract_id}/confirm", response_model=ContractRead)
def confirm_contract_revision(
    contract_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ContractRead:
    result = confirm_revision(session, contract_id, user)
    session.commit()
    return result


@router.post("/contracts/{contract_id}/simulate", response_model=SupervisorSimulation)
def simulate_contract(
    contract_id: UUID,
    source: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> SupervisorSimulation:
    contract = session.get(WritingContract, str(contract_id))
    if contract is None:
        raise AppError("not_found", "Writing contract not found", 404)
    from app.projects.permissions import ProjectAction, require_project_permission

    require_project_permission(UUID(contract.project_id), ProjectAction.view, user, session)
    revision = session.scalar(select(WritingContractRevision).where(WritingContractRevision.contract_id == contract.id, WritingContractRevision.revision == contract.active_revision))
    if revision is None:
        raise AppError("internal_error", "Contract revision missing", 500)
    return simulate_supervisor_review(revision, source)
