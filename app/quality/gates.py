from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import AppError
from app.knowledge.models import KnowledgeSpaceKind


@dataclass(frozen=True)
class QualityGateResult:
    status: str
    findings: list[dict]
    policy_version: str


def evaluate_quality_gate(
    findings: list[dict], *, policy_version: str = "quality-gate-v1"
) -> QualityGateResult:
    normalized = [dict(item) for item in findings]
    if any(
        item.get("severity") == "high" and item.get("mandatory", True)
        for item in normalized
    ):
        return QualityGateResult("failed", normalized, policy_version)
    if any(item.get("human_review_required") for item in normalized):
        return QualityGateResult("needs_human_review", normalized, policy_version)
    return QualityGateResult("passed", normalized, policy_version)


def validate_promotion_target(kind: KnowledgeSpaceKind) -> None:
    if kind not in {KnowledgeSpaceKind.shared, KnowledgeSpaceKind.standard}:
        raise AppError(
            "validation_error",
            "Promotion target must be shared or standard knowledge",
            422,
        )
