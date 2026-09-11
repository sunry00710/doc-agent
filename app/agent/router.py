from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.loop import AgentContext, AgentResult, AgentRunner
from app.agent.tools import ToolRegistry
from app.core.errors import AppError
from app.db.session import get_db
from app.documents.models import Document, DocumentVersion
from app.documents.router import get_storage
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.knowledge.agent_tools import register_knowledge_tools
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.knowledge.promotion_tools import register_promotion_tools
from app.projects.models import ProjectMember
from app.projects.permissions import ProjectAction, require_project_permission
from app.providers.fake import FakeProvider
from app.quality.tools import register_quality_tools

router = APIRouter(prefix="/api", tags=["agent"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=32_000)
    project_id: UUID | None = None
    document_version_id: UUID | None = None
    knowledge_space_ids: list[UUID] = Field(default_factory=list, max_length=32)
    confirmed: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ChatResponse(AgentResult):
    pass


def get_runner(request: Request) -> AgentRunner:
    provider = getattr(request.app.state, "agent_provider", None)
    if provider is None:
        provider = FakeProvider()
    registry = getattr(request.app.state, "agent_tools", None)
    if registry is None:
        registry = ToolRegistry()
        register_quality_tools(registry)
        register_promotion_tools(registry)
        register_knowledge_tools(registry)
    return AgentRunner(provider, registry)


def _authorize_knowledge_space(space: KnowledgeSpace, user: User, session: Session) -> bool:
    if space.kind == KnowledgeSpaceKind.personal:
        return space.owner_id == user.id
    if space.kind == KnowledgeSpaceKind.project:
        if space.project_id is None:
            return False
        membership = session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == space.project_id,
                ProjectMember.user_id == user.id,
            )
        )
        return membership is not None
    return space.kind in (KnowledgeSpaceKind.shared, KnowledgeSpaceKind.standard)


def authorize_context(
    data: ChatRequest,
    user: User,
    session: Session,
    storage: FileStorage,
    request_id: str | None,
) -> AgentContext:
    if data.project_id is not None:
        require_project_permission(data.project_id, ProjectAction.view, user, session)
    if data.document_version_id is not None:
        version = session.get(DocumentVersion, str(data.document_version_id))
        if version is None:
            raise AppError("not_found", "Document version not found", 404)
        document = session.get(Document, version.document_id)
        if document is None:
            raise AppError("not_found", "Document not found", 404)
        require_project_permission(UUID(document.project_id), ProjectAction.view, user, session)
        if data.project_id is not None and document.project_id != str(data.project_id):
            raise AppError("validation_error", "Document version is outside project context", 422)
    for space_id in data.knowledge_space_ids:
        space = session.get(KnowledgeSpace, str(space_id))
        if space is None:
            raise AppError("not_found", "Knowledge space not found", 404)
        if not _authorize_knowledge_space(space, user, session):
            raise AppError("permission_denied", "Knowledge space access denied", 403)
    permissions = frozenset({"document:read"})
    return AgentContext(
        project_id=data.project_id,
        document_version_id=data.document_version_id,
        knowledge_space_ids=tuple(data.knowledge_space_ids),
        permissions=permissions,
        confirmed=data.confirmed,
        idempotency_key=data.idempotency_key,
        actor_id=str(user.id),
        request_id=request_id,
        session=session,
        actor=user,
        storage=storage,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    data: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
    request: Request,
    runner: Annotated[AgentRunner, Depends(get_runner)],
) -> ChatResponse:
    result = runner.run(
        current_user, data.text, authorize_context(data, current_user, session, storage, str(request.state.request_id))
    )
    if result.stop_reason == "provider_unavailable":
        raise AppError("provider_unavailable", "Model provider unavailable", 503, retryable=True)
    if result.stop_reason == "provider_invalid_response":
        raise AppError("provider_invalid_response", "Model provider returned an invalid response", 502)
    return ChatResponse.model_validate(result.model_dump())
