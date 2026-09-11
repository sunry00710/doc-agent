from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import AppError
from app.knowledge.models import KnowledgeSpaceKind
from app.quality.contracts import ContractAssessment
from app.quality.models import WritingContractRevision


@dataclass(frozen=True)
class QualityGateResult:
    status: str
    findings: list[dict]
    policy_version: str


CONTRACT_GATE_POLICY_VERSION = "promotion-contract-gate-v2"


def contract_findings(
    contract_id: str,
    revision: WritingContractRevision,
    assessments: list[ContractAssessment],
) -> list[dict]:
    findings: list[dict] = []
    for assessment in assessments:
        if assessment.status == "satisfied":
            continue
        findings.append(
            {
                "category": "contract_requirement",
                "summary": f"未满足写作要求：{assessment.requirement_id}",
                "evidence": assessment.evidence,
                "requirement_id": assessment.requirement_id,
                "contract_id": contract_id,
                "contract_revision": revision.revision,
                "status": assessment.status,
                "severity": "high" if assessment.mandatory else "medium",
                "mandatory": assessment.mandatory,
                "blocking": assessment.blocking,
                "human_review_required": not assessment.blocking,
            }
        )
    return findings


def evaluate_quality_gate(
    findings: list[dict], *, policy_version: str = "quality-gate-v1"
) -> QualityGateResult:
    normalized = [dict(item) for item in findings]
    if any(
        item.get("blocking") is True
        or (item.get("severity") == "high" and item.get("mandatory", True))
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
