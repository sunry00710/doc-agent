from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.documents.service import read_version
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.roles import can_govern_knowledge
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import (
    KnowledgeDocument,
    KnowledgeSpace,
    KnowledgeState,
)
from app.knowledge.promotion import PromotionRequest, PromotionStatus
from app.projects.permissions import ProjectAction, require_project_permission
from app.quality.contracts import assess_contract
from app.quality.gates import (
    CONTRACT_GATE_POLICY_VERSION,
    contract_findings,
    evaluate_quality_gate,
    validate_promotion_target,
)
from app.quality.models import WritingContract, WritingContractRevision


def _get_version(session: Session, version_id: UUID) -> DocumentVersion:
    version = session.get(DocumentVersion, str(version_id))
    if version is None:
        raise AppError("not_found", "Document version not found", 404)
    return version


def request_promotion(
    session: Session,
    version_id: UUID,
    target_space_id: UUID,
    actor: User,
    storage: FileStorage,
) -> PromotionRequest:
    version = _get_version(session, version_id)
    document = session.get(Document, version.document_id)
    target = session.get(KnowledgeSpace, str(target_space_id))
    if document is None or target is None:
        raise AppError("not_found", "Promotion source or target not found", 404)
    require_project_permission(
        UUID(document.project_id), ProjectAction.submit, actor, session
    )
    validate_promotion_target(target.kind)

    findings: list[dict] = []
    policy_version = "quality-gate-v1"
    contract = session.scalar(
        select(WritingContract).where(WritingContract.document_id == document.id)
    )
    if contract is not None:
        revision = session.scalar(
            select(WritingContractRevision).where(
                WritingContractRevision.contract_id == contract.id,
                WritingContractRevision.revision == contract.active_revision,
            )
        )
        if revision is None:
            raise AppError("internal_error", "Contract revision missing", 500)
        source = read_version(
            session, storage, UUID(document.id), version.number, actor
        ).decode("utf-8")
        assessments = assess_contract(revision, source)
        findings = contract_findings(contract.id, revision, assessments)
        if not revision.reviewer_confirmed:
            findings.append(
                {
                    "category": "contract_unconfirmed",
                    "summary": "写作契约尚未完成评审确认",
                    "evidence": "",
                    "requirement_id": None,
                    "contract_id": contract.id,
                    "contract_revision": revision.revision,
                    "status": "unknown",
                    "severity": "medium",
                    "mandatory": False,
                    "blocking": False,
                    "human_review_required": True,
                }
            )
        policy_version = CONTRACT_GATE_POLICY_VERSION

    gate = evaluate_quality_gate(findings, policy_version=policy_version)
    if gate.status == "failed":
        raise AppError(
            "validation_error",
            "Promotion is blocked by quality gate",
            422,
            details={"findings": gate.findings},
        )
    existing = session.scalars(
        select(PromotionRequest)
        .where(
            PromotionRequest.version_id == version.id,
            PromotionRequest.target_space_id == target.id,
        )
        .order_by(PromotionRequest.created_at.desc(), PromotionRequest.id.desc())
    ).first()
    if existing is not None and existing.status != PromotionStatus.revoked:
        return existing
    request = PromotionRequest(
        version_id=version.id,
        target_space_id=target.id,
        requested_by=actor.id,
        status=PromotionStatus.pending_review,
        quality_status=gate.status,
        findings=gate.findings,
        policy_version=gate.policy_version,
        authority_level=0,
        public_authority=False,
    )
    session.add(request)
    session.flush()
    return request


def review_promotion(
    session: Session, request_id: UUID, actor: User, approved: bool
) -> PromotionRequest:
    request = session.get(PromotionRequest, str(request_id))
    if request is None:
        raise AppError("not_found", "Promotion request not found", 404)
    version = _get_version(session, UUID(request.version_id))
    document = session.get(Document, version.document_id)
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(
        UUID(document.project_id), ProjectAction.review, actor, session
    )
    if not can_govern_knowledge(actor):
        raise AppError("permission_denied", "Reviewer approval required", 403)
    if request.status not in {PromotionStatus.pending_review, PromotionStatus.approved}:
        return request
    request.status = PromotionStatus.approved if approved else PromotionStatus.rejected
    request.reviewed_by = actor.id
    request.reviewed_at = datetime.now(UTC)
    session.flush()
    return request


def activate_promotion(
    session: Session,
    request_id: UUID,
    storage: FileStorage,
    actor: User,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> PromotionRequest:
    request = session.get(PromotionRequest, str(request_id))
    if request is None:
        raise AppError("not_found", "Promotion request not found", 404)
    version = _get_version(session, UUID(request.version_id))
    source_document = session.get(Document, version.document_id)
    if source_document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(
        UUID(source_document.project_id), ProjectAction.review, actor, session
    )
    if not can_govern_knowledge(actor):
        raise AppError("permission_denied", "Reviewer approval required", 403)
    if request.status != PromotionStatus.approved:
        raise AppError("validation_error", "Promotion is not approved", 422)
    request.status = PromotionStatus.indexing
    try:
        document = ingest_version(
            session,
            storage,
            UUID(request.version_id),
            UUID(request.target_space_id),
            embedding_provider=embedding_provider,
        )
    except AppError as exc:
        request.status = PromotionStatus.failed
        request.error = {"code": exc.code, "message": "Knowledge indexing failed"}
        session.flush()
        return request
    document.state = KnowledgeState.indexed
    request.status = PromotionStatus.indexed
    session.flush()
    return request


def revoke_promotion(
    session: Session, request_id: UUID, actor: User
) -> PromotionRequest:
    request = session.get(PromotionRequest, str(request_id))
    if request is None:
        raise AppError("not_found", "Promotion request not found", 404)
    version = _get_version(session, UUID(request.version_id))
    document = session.get(Document, version.document_id)
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(
        UUID(document.project_id), ProjectAction.review, actor, session
    )
    if not can_govern_knowledge(actor):
        raise AppError("permission_denied", "Reviewer approval required", 403)
    request.status = PromotionStatus.revoked
    document = session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.version_id == request.version_id,
            KnowledgeDocument.space_id == request.target_space_id,
        )
    )
    if document is not None:
        document.state = KnowledgeState.archived
        # 撤销后立即切断可检索的 generation，避免 FTS/Dense 仍返回旧内容
        document.active_generation_id = None
    session.flush()
    return request
