import pytest

from app.quality.schemas import Finding, FindingSummary, normalize_findings


def finding(**changes) -> Finding:
    data = {
        "id": "one",
        "category": "style",
        "severity": "medium",
        "start_offset": 0,
        "end_offset": 2,
        "evidence": "原文",
        "explanation": "说明",
        "suggested_action": "修改",
        "citation_ids": [],
        "confidence": 0.8,
        "mandatory": False,
        "human_review_required": False,
    }
    data.update(changes)
    return Finding(**data)


def test_normalization_merges_overlapping_category_duplicates_and_flags_logical_candidates():
    normalized = normalize_findings("原文内容", [finding(), finding(id="two", start_offset=1, end_offset=2, evidence="文", explanation="另一个说明"), finding(id="three", category="logical_mismatch", start_offset=2, end_offset=4, evidence="内容")])

    assert len(normalized) == 2
    assert normalized[0].id == "one"
    assert normalized[1].human_review_required is True


def test_normalization_rejects_invalid_source_evidence_and_summary_mismatch():
    with pytest.raises(ValueError, match="evidence"):
        normalize_findings("原文", [finding(evidence="伪造")])
    with pytest.raises(ValueError, match="summary"):
        FindingSummary(total=2, low=0, medium=1, high=0).validate_against([finding()])
