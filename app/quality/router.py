from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.identity.models import User
from app.identity.router import get_current_user
from app.quality.contracts import (
    ContractRead,
    ContractRevisionInput,
    confirm_revision,
    create_contract,
    create_revision,
)
from app.quality.models import WritingContract, WritingContractRevision
from app.quality.supervisor import SupervisorSimulation, simulate_supervisor_review

router = APIRouter(prefix="/api/quality", tags=["quality"])


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
