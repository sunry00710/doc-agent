from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    severity: Literal["low", "medium", "high"]
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    evidence: str = Field(min_length=1, max_length=8_000)
    explanation: str = Field(min_length=1, max_length=8_000)
    suggested_action: str | None = Field(default=None, max_length=8_000)
    citation_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0, le=1)
    mandatory: bool
    human_review_required: bool

    @model_validator(mode="after")
    def valid_range(self) -> Finding:
        if self.end_offset <= self.start_offset:
            raise ValueError("source range is invalid")
        if self.category == "logical_mismatch":
            self.human_review_required = True
        return self


class FindingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)

    def validate_against(self, findings: list[Finding]) -> None:
        counts = {level: sum(item.severity == level for item in findings) for level in ("low", "medium", "high")}
        if (self.total, self.low, self.medium, self.high) != (
            len(findings), counts["low"], counts["medium"], counts["high"]
        ):
            raise ValueError("summary counts do not match findings")


class QualityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(default_factory=list)
    summary: FindingSummary
    coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_summary(self) -> QualityResponse:
        self.summary.validate_against(self.findings)
        return self


class RewriteSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_range: tuple[int, int]
    original: str
    suggestion: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    citation_ids: list[str] = Field(default_factory=list)


class ComparisonChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    summary: str
    # 语义对比补充信息：原文片段、影响说明，以及改动前后是否语义等价
    old_text: str = ""
    new_text: str = ""
    impact: str = ""
    semantic_equivalent: bool | None = None
    version_a_id: str
    version_b_id: str
    citations: list[str] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[ComparisonChange]
    summary: str
    citations: list[str] = Field(default_factory=list)


def normalize_findings(source: str, findings: list[Finding]) -> list[Finding]:
    accepted: list[Finding] = []
    for finding in sorted(findings, key=lambda item: (item.start_offset, item.end_offset, item.id)):
        if finding.end_offset > len(source) or source[finding.start_offset:finding.end_offset] != finding.evidence:
            raise ValueError("finding evidence does not match source")
        duplicate = next(
            (
                item
                for item in accepted
                if item.category == finding.category
                and item.start_offset < finding.end_offset
                and finding.start_offset < item.end_offset
            ),
            None,
        )
        if duplicate is None:
            accepted.append(finding)
    return accepted
