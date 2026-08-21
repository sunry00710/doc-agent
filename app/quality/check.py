from __future__ import annotations

from collections.abc import Iterable

from app.quality.schemas import Finding, QualityResponse, normalize_findings


def normalize_quality_response(source: str, response: QualityResponse) -> QualityResponse:
    findings = normalize_findings(source, response.findings)
    summary = response.summary.model_copy(deep=True)
    summary.validate_against(findings)
    return response.model_copy(update={"findings": findings, "summary": summary})


def check(source: str, findings: Iterable[Finding] | QualityResponse) -> list[Finding] | QualityResponse:
    if isinstance(findings, QualityResponse):
        return normalize_quality_response(source, findings)
    return normalize_findings(source, list(findings))
