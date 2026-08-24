from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.tools import ToolDefinition, ToolRegistry
from app.core.config import Settings
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.embeddings import FastEmbedProvider
from app.knowledge.schemas import SearchHit, SearchQuery
from app.knowledge.search import search

_embedding_provider = FastEmbedProvider()
_storage: FileStorage | None = None


def _file_storage() -> FileStorage:
    global _storage
    if _storage is None:
        _storage = FileStorage(Settings())
    return _storage


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mode: Literal["keyword", "dense", "hybrid"] = "keyword"
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hits: list[SearchHit]
    total: int


def _search_handler(data: KnowledgeSearchInput, context: Any) -> KnowledgeSearchOutput:
    session = getattr(context, "session", None)
    actor = getattr(context, "actor", None)
    if not isinstance(session, Session) or not isinstance(actor, User):
        raise TypeError("Knowledge search requires an authenticated database context")
    # 授权范围由 search() 内部按空间分级过滤：个人库（本人）+ 项目库（成员）+ 共享/规范库；
    # 会话通过 chat 的 knowledge_space_ids 限定子集时进一步收窄
    space_ids = getattr(context, "knowledge_space_ids", None) or ()
    allowed_space_ids = frozenset(str(UUID(str(space_id))) for space_id in space_ids) if space_ids else None
    query = SearchQuery(query=data.query, mode=data.mode, limit=data.limit)
    hits = search(session, _file_storage(), query, actor, embedding_provider=_embedding_provider, allowed_space_ids=allowed_space_ids)
    return KnowledgeSearchOutput(hits=list(hits), total=len(hits))


def register_knowledge_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="search_knowledge",
            description="Search indexed knowledge sources the current user is authorized to read",
            input_model=KnowledgeSearchInput,
            handler=_search_handler,
            output_model=KnowledgeSearchOutput,
        )
    )


__all__ = ["KnowledgeSearchInput", "KnowledgeSearchOutput", "register_knowledge_tools"]
