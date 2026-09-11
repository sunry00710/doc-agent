from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent.tools import ToolDefinition, ToolRegistry
from app.documents.models import DocumentVersion
from app.documents.service import read_version
from app.documents.storage import FileStorage
from app.identity.models import User
from app.quality.check import check
from app.quality.compare import compare_documents
from app.quality.judge import judge_document
from app.quality.review import ReviewSuggestion, review_comments
from app.quality.rewrite import rewrite_suggestion
from app.quality.schemas import ComparisonResult, Finding, QualityResponse


class QualityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 省略时从会话绑定的 document_version_id 读取真实正文（绑定优先，防止模型改错文件）
    source: str | None = Field(default=None, max_length=200_000)
    response: QualityResponse


class FindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, max_length=200_000)
    findings: list[Finding] = Field(max_length=1_000)


class CompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: ComparisonResult
    version_a_id: str = Field(min_length=1, max_length=128)
    version_b_id: str = Field(min_length=1, max_length=128)


def _bound_source(context: Any) -> str | None:
    """读取对话绑定的文档版本正文；未绑定或无法读取时返回 None（回退到模型提供的 source）。"""
    version_id = getattr(context, "document_version_id", None)
    session = getattr(context, "session", None)
    actor = getattr(context, "actor", None)
    if version_id is None or not isinstance(session, Session) or not isinstance(actor, User):
        return None
    version = session.get(DocumentVersion, str(version_id))
    if version is None:
        return None
    storage = getattr(context, "storage", None)
    if not isinstance(storage, FileStorage):
        return None
    try:
        return read_version(session, storage, UUID(version.document_id), version.number, actor).decode("utf-8")
    except Exception:  # noqa: BLE001 - 绑定读取失败时回退模型 source，不阻断工具调用
        return None


def _resolve_source(data_source: str | None, context: Any) -> str:
    bound = _bound_source(context)
    if bound is not None:
        return bound
    if data_source:
        return data_source
    raise ValueError("source is required when no document version is bound to the conversation")


def _check(data: QualityInput, context: Any) -> QualityResponse:
    return check(_resolve_source(data.source, context), data.response)  # type: ignore[return-value]


def _rewrite(data: FindingInput, context: Any) -> list[object]:
    return rewrite_suggestion(_resolve_source(data.source, context), data.findings)


def _compare(data: CompareInput, _context: Any) -> ComparisonResult:
    return compare_documents(data.result, data.version_a_id, data.version_b_id)


def _judge(data: QualityInput, context: Any) -> QualityResponse:
    return judge_document(_resolve_source(data.source, context), data.response)


def _review(data: ReviewSuggestion, _context: Any) -> ReviewSuggestion:
    return review_comments(data)


def _trace(_model: BaseModel, result: object) -> object:
    if isinstance(result, list):
        return {"count": len(result)}
    if isinstance(result, BaseModel):
        return {"fields": sorted(result.model_fields_set)}
    return {"type": type(result).__name__}


def register_quality_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="check_document",
            description="Validate structured document findings",
            input_model=QualityInput,
            handler=_check,
            output_model=QualityResponse,
        )
    )
    registry.register(
        ToolDefinition(
            name="rewrite_suggestion",
            description="Validate source-bound rewrite suggestions",
            input_model=FindingInput,
            handler=_rewrite,
        )
    )
    registry.register(
        ToolDefinition(
            name="compare_documents",
            description="Validate version comparison bindings",
            input_model=CompareInput,
            handler=_compare,
            output_model=ComparisonResult,
        )
    )
    registry.register(
        ToolDefinition(
            name="review_comments",
            description="Structure review comment guidance",
            input_model=ReviewSuggestion,
            handler=_review,
            output_model=ReviewSuggestion,
        )
    )
    registry.register(
        ToolDefinition(
            name="judge_document",
            description="Validate structured document judgement",
            input_model=QualityInput,
            handler=_judge,
            output_model=QualityResponse,
        )
    )
