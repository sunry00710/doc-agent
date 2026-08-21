from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import (
    KnowledgeDocument,
    KnowledgeSpace,
    KnowledgeState,
)
from app.knowledge.promotion import PromotionRequest, PromotionStatus
from app.projects.permissions import ProjectAction, require_project_permission
from app.quality.gates import (
    QualityGateResult,
    validate_promotion_target,
)


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
    gate: QualityGateResult,
    *,
    public_authority: bool = False,
    authority_level: int = 0,
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
    if gate.status not in {"passed", "needs_human_review"}:
        raise AppError("validation_error", "Invalid quality gate result", 422)
    existing = session.scalar(
        select(PromotionRequest).where(
            PromotionRequest.version_id == version.id,
            PromotionRequest.target_space_id == target.id,
        )
    )
    if existing is not None:
        return existing
    status = (
        PromotionStatus.approved
        if public_authority and gate.status == "passed"
        else PromotionStatus.pending_review
    )
    request = PromotionRequest(
        version_id=version.id,
        target_space_id=target.id,
        requested_by=actor.id,
        status=status,
        quality_status=gate.status,
        findings=gate.findings,
        policy_version=gate.policy_version,
        authority_level=authority_level,
        public_authority=public_authority,
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
    if actor.role not in {Role.reviewer, Role.admin}:
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
    if actor.role not in {Role.reviewer, Role.admin}:
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
    if actor.role not in {Role.reviewer, Role.admin}:
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
    session.flush()
    return request
