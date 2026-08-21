from __future__ import annotations

from app.quality.schemas import ComparisonResult


def compare_documents(result: ComparisonResult, version_a_id: str, version_b_id: str) -> ComparisonResult:
    for change in result.changes:
        if change.version_a_id != version_a_id or change.version_b_id != version_b_id:
            raise ValueError("comparison change is not bound to requested versions")
    return result
