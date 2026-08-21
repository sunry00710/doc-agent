from __future__ import annotations

from collections.abc import Iterable

from app.quality.schemas import Finding, RewriteSuggestion, normalize_findings


def rewrite_suggestion(source: str, findings: Iterable[Finding]) -> list[RewriteSuggestion]:
    normalized = normalize_findings(source, list(findings))
    return [
        RewriteSuggestion(
            source_range=(item.start_offset, item.end_offset),
            original=item.evidence,
            suggestion=item.suggested_action or item.evidence,
            reason=item.explanation,
            citation_ids=item.citation_ids,
        )
        for item in normalized
    ]
