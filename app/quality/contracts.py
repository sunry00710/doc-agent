from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document
from app.identity.models import User
from app.projects.permissions import ProjectAction, require_project_permission
from app.quality.models import WritingContract, WritingContractRevision


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8_000)
    mandatory: bool = True


class ContractRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=255)
    subject_organization: str = Field(min_length=1, max_length=255)
    reporting_period: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=8_000)
    audience: str = Field(min_length=1, max_length=8_000)
    requirements: list[Requirement] = Field(max_length=100)
    standard_ids: list[UUID] = Field(default_factory=list, max_length=100)
    precedent_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reviewer_id: UUID | None = None


class ContractRevisionRead(ContractRevisionInput):
    revision: int
    reviewer_confirmed: bool


class ContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    document_id: UUID
    active_revision: int
    revision: ContractRevisionRead


def _to_revision_input(revision: WritingContractRevision) -> ContractRevisionInput:
    return ContractRevisionInput(
        domain=revision.domain,
        document_type=revision.document_type,
        subject_organization=revision.subject_organization,
        reporting_period=revision.reporting_period,
        purpose=revision.purpose,
        audience=revision.audience,
        requirements=[Requirement.model_validate(item) for item in revision.requirements],
        standard_ids=[UUID(item) for item in revision.standard_ids],
        precedent_ids=[UUID(item) for item in revision.precedent_ids],
        reviewer_id=UUID(revision.reviewer_id) if revision.reviewer_id else None,
    )


def contract_read(contract: WritingContract, revision: WritingContractRevision) -> ContractRead:
    data = _to_revision_input(revision)
    return ContractRead(
        id=UUID(contract.id),
        project_id=UUID(contract.project_id),
        document_id=UUID(contract.document_id),
        active_revision=contract.active_revision,
        revision=ContractRevisionRead(**data.model_dump(), revision=revision.revision, reviewer_confirmed=revision.reviewer_confirmed),
    )


def get_contract_document(session: Session, document_id: UUID, user: User) -> Document:
    document = session.get(Document, str(document_id))
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(UUID(document.project_id), ProjectAction.view, user, session)
    return document


def create_contract(session: Session, document_id: UUID, data: ContractRevisionInput, user: User) -> ContractRead:
    document = get_contract_document(session, document_id, user)
    if session.scalar(select(WritingContract).where(WritingContract.document_id == str(document_id))) is not None:
        raise AppError("conflict", "Writing contract already exists", 409)
    contract = WritingContract(project_id=document.project_id, document_id=str(document_id), created_by=str(user.id))
    session.add(contract)
    session.flush()
    revision = _revision_model(contract, data, user, 1)
    session.add(revision)
    session.flush()
    return contract_read(contract, revision)


def create_revision(session: Session, contract_id: UUID, data: ContractRevisionInput, user: User) -> ContractRead:
    contract = session.get(WritingContract, str(contract_id))
    if contract is None:
        raise AppError("not_found", "Writing contract not found", 404)
    require_project_permission(UUID(contract.project_id), ProjectAction.edit, user, session)
    revision_number = contract.active_revision + 1
    revision = _revision_model(contract, data, user, revision_number)
    contract.active_revision = revision_number
    session.add(revision)
    session.flush()
    return contract_read(contract, revision)


def confirm_revision(session: Session, contract_id: UUID, user: User) -> ContractRead:
    contract = session.get(WritingContract, str(contract_id))
    if contract is None:
        raise AppError("not_found", "Writing contract not found", 404)
    require_project_permission(UUID(contract.project_id), ProjectAction.review, user, session)
    revision = session.scalar(select(WritingContractRevision).where(WritingContractRevision.contract_id == contract.id, WritingContractRevision.revision == contract.active_revision))
    if revision is None:
        raise AppError("internal_error", "Contract revision missing", 500)
    revision.reviewer_id = str(user.id)
    revision.reviewer_confirmed = True
    session.flush()
    return contract_read(contract, revision)


def _revision_model(contract: WritingContract, data: ContractRevisionInput, user: User, number: int) -> WritingContractRevision:
    return WritingContractRevision(
        contract_id=contract.id,
        revision=number,
        domain=data.domain,
        document_type=data.document_type,
        subject_organization=data.subject_organization,
        reporting_period=data.reporting_period,
        purpose=data.purpose,
        audience=data.audience,
        requirements=[item.model_dump(mode="json") for item in data.requirements],
        standard_ids=[str(item) for item in data.standard_ids],
        precedent_ids=[str(item) for item in data.precedent_ids],
        reviewer_id=str(data.reviewer_id) if data.reviewer_id else None,
        created_by=str(user.id),
    )


class ContractAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    status: Literal["satisfied", "unsatisfied", "unknown"]
    evidence: str = ""
    mandatory: bool = True
    blocking: bool = True


def assess_contract(revision: WritingContractRevision, source: str) -> list[ContractAssessment]:
    assessments = []
    for item in revision.requirements:
        requirement = Requirement.model_validate(item)
        status: Literal["satisfied", "unsatisfied", "unknown"] = "satisfied" if requirement.text in source else "unsatisfied"
        assessments.append(ContractAssessment(requirement_id=requirement.id, status=status, evidence=requirement.text if status == "satisfied" else "", mandatory=requirement.mandatory, blocking=requirement.mandatory and status != "satisfied"))
    return assessments
