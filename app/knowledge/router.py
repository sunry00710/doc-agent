from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.documents.models import Document, DocumentVersion
from app.documents.router import get_storage
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.knowledge.embeddings import FastEmbedProvider
from app.knowledge.models import KnowledgeSpace
from app.knowledge.promotion import PromotionRequest
from app.knowledge.promotion_schemas import PromotionRead
from app.knowledge.schemas import (
    KnowledgeSpaceList,
    KnowledgeSpaceRead,
    PromotionList,
    SearchHit,
    SearchQuery,
)
from app.knowledge.search import search
from app.projects.models import ProjectMember

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
_embedding_provider = FastEmbedProvider()


@router.get("/spaces", response_model=KnowledgeSpaceList)
def list_spaces(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> KnowledgeSpaceList:
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
    spaces = session.scalars(select(KnowledgeSpace).where((KnowledgeSpace.kind.in_(["shared", "standard"])) | (KnowledgeSpace.owner_id == current_user.id) | KnowledgeSpace.project_id.in_(project_ids)).order_by(KnowledgeSpace.kind, KnowledgeSpace.id)).all()
    return KnowledgeSpaceList(items=[KnowledgeSpaceRead.model_validate(space) for space in spaces])


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
    return PromotionList(items=[PromotionRead.model_validate(item) for item in requests])


@router.post("/search", response_model=list[SearchHit])
def search_knowledge(
    query: SearchQuery,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> list[SearchHit]:
    return search(session, storage, query, current_user, embedding_provider=_embedding_provider)
