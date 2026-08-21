from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools import ToolDefinition, ToolRegistry
from app.quality.check import check
from app.quality.compare import compare_documents
from app.quality.judge import judge_document
from app.quality.review import ReviewSuggestion, review_comments
from app.quality.rewrite import rewrite_suggestion
from app.quality.schemas import ComparisonResult, Finding, QualityResponse


class QualityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200_000)
    response: QualityResponse


class FindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200_000)
    findings: list[Finding] = Field(max_length=1_000)


class CompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: ComparisonResult
    version_a_id: str = Field(min_length=1, max_length=128)
    version_b_id: str = Field(min_length=1, max_length=128)


def _check(data: QualityInput, _context: Any) -> QualityResponse:
    return check(data.source, data.response)  # type: ignore[return-value]


def _rewrite(data: FindingInput, _context: Any) -> list[object]:
    return rewrite_suggestion(data.source, data.findings)


def _compare(data: CompareInput, _context: Any) -> ComparisonResult:
    return compare_documents(data.result, data.version_a_id, data.version_b_id)


def _judge(data: QualityInput, _context: Any) -> QualityResponse:
    return judge_document(data.source, data.response)


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
