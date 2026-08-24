from __future__ import annotations

from app.quality.compare import compare_documents
from app.quality.schemas import ComparisonChange, ComparisonResult, Finding
from tests.evaluation.metrics import (
    citation_correctness,
    comparison_coverage,
    duplicate_finding_rate,
    recall_at_6,
)


def test_public_audit_baseline_metrics_are_deterministic():
    assert recall_at_6([["scope-1"], ["other"]], [["scope-1"], ["finding-1"]]) == 0.5
    assert citation_correctness([{"quote": "审计范围明确"}], [["审计范围"]]) == 1.0
    assert (
        comparison_coverage(
            ComparisonResult(
                changes=[
                    ComparisonChange(
                        category="structure",
                        summary="x",
                        version_a_id="a",
                        version_b_id="b",
                    )
                ],
                summary="x",
            ),
            {"structure", "data"},
        )
        == 0.5
    )


def test_duplicate_finding_rate_and_bound_comparison():
    findings = [
        Finding(
            id="a",
            category="grammar",
            severity="low",
            start_offset=0,
            end_offset=2,
            evidence="ab",
            explanation="x",
            confidence=0.9,
            mandatory=False,
            human_review_required=False,
        ),
        Finding(
            id="b",
            category="grammar",
            severity="low",
            start_offset=1,
            end_offset=3,
            evidence="bc",
            explanation="x",
            confidence=0.9,
            mandatory=False,
            human_review_required=False,
        ),
    ]
    assert duplicate_finding_rate(findings) == 0.5
    result = ComparisonResult(
        changes=[
            ComparisonChange(
                category="data", summary="x", version_a_id="a", version_b_id="b"
            )
        ],
        summary="x",
    )
    assert compare_documents(result, "a", "b") == result
