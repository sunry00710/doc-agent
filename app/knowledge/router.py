from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.documents.models import Document, DocumentVersion
from app.documents.router import get_storage
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.identity.router import get_current_user
from app.knowledge.embeddings import FastEmbedProvider
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind, KnowledgeState
from app.knowledge.promotion import PromotionRequest
from app.knowledge.promotion_schemas import PromotionRead
from app.knowledge.schemas import (
    IngestResult,
    KnowledgeSpaceList,
    KnowledgeSpaceRead,
    PromotionList,
    SearchHit,
    SearchQuery,
    SpaceCreate,
    SpaceIngest,
)
from app.knowledge.search import search
from app.projects.models import ProjectMember
from app.projects.permissions import (
    ROLE_ACTIONS,
    ProjectAction,
    require_project_permission,
)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _enriched_promotion(session: Session, request: PromotionRequest, governable_projects: set[str]) -> PromotionRead:
    """填充 document_title/version_number，前端可显示《标题》vN 而非裸 UUID。"""
    read = PromotionRead.model_validate(request)
    row = session.execute(
        select(Document.title, DocumentVersion.number, Document.project_id)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(DocumentVersion.id == request.version_id)
    ).first()
    if row is not None:
        read.document_title = row.title
        read.version_number = row.number
        read.can_govern = row.project_id in governable_projects
    return read


@router.get("/spaces", response_model=KnowledgeSpaceList)
def list_spaces(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> KnowledgeSpaceList:
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
    spaces = session.scalars(select(KnowledgeSpace).where((KnowledgeSpace.kind.in_(["shared", "standard"])) | (KnowledgeSpace.owner_id == current_user.id) | KnowledgeSpace.project_id.in_(project_ids)).order_by(KnowledgeSpace.kind, KnowledgeSpace.id)).all()
    return KnowledgeSpaceList(items=[KnowledgeSpaceRead.model_validate(space) for space in spaces])


@router.post("/spaces", response_model=KnowledgeSpaceRead, status_code=201)
def create_space(
    data: SpaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> KnowledgeSpaceRead:
    # 个人知识库自助创建；幂等：已存在则直接返回现有空间
    existing = session.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.kind == KnowledgeSpaceKind.personal,
            KnowledgeSpace.owner_id == current_user.id,
        )
    )
    if existing is not None:
        return KnowledgeSpaceRead.model_validate(existing)
    space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=current_user.id)
    session.add(space)
    session.commit()
    session.refresh(space)
    return KnowledgeSpaceRead.model_validate(space)


def _embedding_provider_for(request: Request) -> FastEmbedProvider | None:
    """按配置返回 embedding provider；embedding_enabled=false 时返回 None（纯关键词模式）。"""
    settings = request.app.state.settings
    if not settings.embedding_enabled:
        return None
    return FastEmbedProvider(model_name=settings.embedding_model)


@router.post("/spaces/{space_id}/ingest", response_model=IngestResult, status_code=201)
def ingest_into_space(
    request: Request,
    space_id: UUID,
    data: SpaceIngest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> IngestResult:
    space = session.get(KnowledgeSpace, str(space_id))
    if space is None:
        raise AppError("not_found", "Knowledge space not found", 404)
    if space.kind != KnowledgeSpaceKind.personal or space.owner_id != current_user.id:
        raise AppError("permission_denied", "Only the owner can ingest into a personal space", 403)
    version = session.get(DocumentVersion, str(data.version_id))
    if version is None:
        raise AppError("not_found", "Document version not found", 404)
    document = session.get(Document, version.document_id)
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(UUID(document.project_id), ProjectAction.view, current_user, session)
    knowledge_document = ingest_version(
        session,
        storage,
        UUID(version.id),
        UUID(space.id),
        embedding_provider=_embedding_provider_for(request),
    )
    knowledge_document.state = KnowledgeState.indexed
    session.commit()
    return IngestResult(
        document_id=UUID(knowledge_document.id),
        space_id=UUID(space.id),
        version_id=UUID(version.id),
        state=knowledge_document.state.value,
    )


@router.get("/promotions", response_model=PromotionList)
def list_promotions(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    version_id: str | None = None,
) -> PromotionList:
    statement = select(PromotionRequest).join(KnowledgeSpace, KnowledgeSpace.id == PromotionRequest.target_space_id)
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
    statement = statement.join_from(PromotionRequest, DocumentVersion, DocumentVersion.id == PromotionRequest.version_id).join(Document, Document.id == DocumentVersion.document_id).where((KnowledgeSpace.kind.in_(["shared", "standard"])) | (Document.project_id.in_(project_ids)))
    if version_id is not None:
        statement = statement.where(PromotionRequest.version_id == version_id)
    requests = session.scalars(statement.order_by(PromotionRequest.created_at.desc())).all()
    governable_projects = set()
    if current_user.role in {Role.reviewer, Role.admin}:
        memberships = session.scalars(select(ProjectMember).where(ProjectMember.user_id == current_user.id))
        governable_projects = {
            member.project_id for member in memberships
            if ProjectAction.review in ROLE_ACTIONS[member.membership_role]
        }
    return PromotionList(items=[_enriched_promotion(session, item, governable_projects) for item in requests])


@router.post("/search", response_model=list[SearchHit])
def search_knowledge(
    request: Request,
    query: SearchQuery,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> list[SearchHit]:
    return search(session, storage, query, current_user, embedding_provider=_embedding_provider_for(request))
