from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.agent.loop import AgentContext
from app.agent.tools import ToolDefinition, ToolRegistry
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.promotion_service import request_promotion


class PromotionToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    target_space_id: UUID


class PromotionToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: str
    quality_status: str


def _promotion_handler(data: PromotionToolInput, context: AgentContext) -> dict[str, object]:
    session = getattr(context, "session", None)
    actor = getattr(context, "actor", None)
    storage = getattr(context, "storage", None)
    if not isinstance(session, Session) or not isinstance(actor, User) or not isinstance(storage, FileStorage):
        raise TypeError("Promotion requires an authenticated database context")
    request = request_promotion(session, data.version_id, data.target_space_id, actor, storage)
    session.commit()
    return {"request_id": request.id, "status": request.status.value, "quality_status": request.quality_status}


def _authorize_promotion(context: Any, _data: PromotionToolInput) -> bool:
    return (
        isinstance(context, AgentContext)
        and getattr(context, "session", None) is not None
        and getattr(context, "actor", None) is not None
        and isinstance(getattr(context, "storage", None), FileStorage)
    )


def register_promotion_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="request_knowledge_promotion",
            description="Request governed promotion of an immutable document version",
            input_model=PromotionToolInput,
            handler=_promotion_handler,
            mutating=True,
            authorizer=_authorize_promotion,
            output_model=PromotionToolOutput,
        )
    )
