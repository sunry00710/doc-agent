from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.loop import AgentContext
from app.agent.tools import ToolDefinition, ToolRegistry
from app.identity.models import User
from app.knowledge.promotion_service import request_promotion
from app.quality.gates import evaluate_quality_gate


class PromotionToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    target_space_id: UUID
    findings: list[dict] = Field(default_factory=list, max_length=1_000)
    public_authority: bool = False
    authority_level: int = Field(default=0, ge=0)


class PromotionToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: str
    quality_status: str


def _promotion_handler(data: PromotionToolInput, context: AgentContext) -> dict[str, object]:
    session = getattr(context, "session", None)
    actor = getattr(context, "actor", None)
    if not isinstance(session, Session) or not isinstance(actor, User):
        raise TypeError("Promotion requires an authenticated database context")
    gate = evaluate_quality_gate(data.findings)
    request = request_promotion(session, data.version_id, data.target_space_id, actor, gate, public_authority=data.public_authority, authority_level=data.authority_level)
    session.commit()
    return {"request_id": request.id, "status": request.status.value, "quality_status": request.quality_status}


def _authorize_promotion(context: Any, _data: PromotionToolInput) -> bool:
    return isinstance(context, AgentContext) and getattr(context, "session", None) is not None and getattr(context, "actor", None) is not None


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
