from __future__ import annotations

from app.quality.schemas import Finding, FindingSummary, QualityResponse


def response(source: str, findings: list[Finding]) -> QualityResponse:
    counts = {level: sum(item.severity == level for item in findings) for level in ("low", "medium", "high")}
    return QualityResponse(
        findings=findings,
        summary=FindingSummary(total=len(findings), low=counts["low"], medium=counts["medium"], high=counts["high"]),
        coverage=1,
    )
