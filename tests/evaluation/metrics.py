from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.quality.schemas import ComparisonResult, Finding

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "evaluation"


def load_fixture(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def recall_at_6(results: list[list[str]], expected: list[list[str]]) -> float:
    if not expected:
        return 1.0
    return sum(
        bool(set(actual[:6]) & set(wanted)) for actual, wanted in zip(results, expected)
    ) / len(expected)


def citation_correctness(
    citations: list[dict[str, Any]], expected_terms: list[list[str]]
) -> float:
    if not expected_terms:
        return 1.0
    correct = 0
    for actual, terms in zip(citations, expected_terms):
        quote = str(actual.get("quote", ""))
        if terms and any(term in quote for term in terms):
            correct += 1
    return correct / len(expected_terms)


def duplicate_finding_rate(findings: list[Finding]) -> float:
    if not findings:
        return 0.0
    duplicate_pairs = 0
    for index, left in enumerate(findings):
        for right in findings[index + 1 :]:
            if (
                left.category == right.category
                and left.start_offset < right.end_offset
                and right.start_offset < left.end_offset
            ):
                duplicate_pairs += 1
    return duplicate_pairs / len(findings)


def comparison_coverage(
    result: ComparisonResult, required_categories: set[str]
) -> float:
    if not required_categories:
        return 1.0
    covered = {change.category for change in result.changes}
    return len(covered & required_categories) / len(required_categories)
