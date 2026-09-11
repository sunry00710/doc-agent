from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
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
from app.providers.base import ModelProvider
from app.quality.compare import compare_documents
from app.quality.comparison import compare_sources
from app.quality.contracts import (
    ContractRead,
    ContractRevisionInput,
    confirm_revision,
    contract_read,
    create_contract,
    create_revision,
    get_contract_document,
)
from app.quality.models import WritingContract, WritingContractRevision
from app.quality.supervisor import SupervisorSimulation, simulate_supervisor_review

router = APIRouter(prefix="/api/quality", tags=["quality"])


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_a_id: UUID
    version_b_id: UUID
    comparison_type: str = Field(min_length=1, max_length=32)


class ComparisonResponse(BaseModel):
    version_a_id: UUID
    version_b_id: UUID
    comparison_type: str
    #: 实际使用的引擎：llm=真实模型语义对比，heuristic=离线启发式，difflib=逐行回退
    engine: Literal["llm", "heuristic", "difflib"]
    degraded: bool = False
    degraded_reason: str | None = None
    truncated: bool = False
    changes: list[dict]
    summary: str
    citations: list[str]


def get_comparison_provider(request: Request) -> ModelProvider | None:
    """对比引擎使用与 Agent 对话同一个 provider；缺失时由引擎回退。"""
    provider = getattr(request.app.state, "agent_provider", None)
    return provider if isinstance(provider, ModelProvider) else None


@router.post("/comparisons", response_model=ComparisonResponse)
def compare_versions(
    data: ComparisonRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
    provider: Annotated[ModelProvider | None, Depends(get_comparison_provider)],
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
    outcome = compare_sources(
        source_a,
        source_b,
        data.comparison_type,
        str(data.version_a_id),
        str(data.version_b_id),
        provider,
    )
    validated = compare_documents(
        outcome.result, str(data.version_a_id), str(data.version_b_id)
    )
    return ComparisonResponse(
        version_a_id=data.version_a_id,
        version_b_id=data.version_b_id,
        comparison_type=data.comparison_type,
        engine=outcome.engine,
        degraded=outcome.degraded,
        degraded_reason=outcome.degraded_reason,
        truncated=outcome.truncated,
        **validated.model_dump(),
    )


@router.get("/documents/{document_id}/contract", response_model=ContractRead)
def read_document_contract(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ContractRead:
    get_contract_document(session, document_id, user)
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
    require_project_permission(UUID(contract.project_id), ProjectAction.view, user, session)
    revision = session.scalar(select(WritingContractRevision).where(WritingContractRevision.contract_id == contract.id, WritingContractRevision.revision == contract.active_revision))
    if revision is None:
        raise AppError("internal_error", "Contract revision missing", 500)
    return simulate_supervisor_review(revision, source)
