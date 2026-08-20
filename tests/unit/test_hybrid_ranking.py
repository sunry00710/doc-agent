import pytest
from app.knowledge.ranking import RankedId, reciprocal_rank_fusion


def ranked(chunk_id: str, generation_id: str, score: float = 0.0) -> RankedId:
    return RankedId(chunk_id=chunk_id, generation_id=generation_id, score=score)


def test_rrf_deduplicates_only_stable_chunk_generation_identity():
    first = [ranked("same", "generation-a"), ranked("other", "generation-a")]
    second = [ranked("same", "generation-b"), ranked("same", "generation-a")]

    fused = reciprocal_rank_fusion([first, second], k=60)

    assert [(item.chunk_id, item.generation_id) for item in fused] == [
        ("same", "generation-a"),
        ("same", "generation-b"),
        ("other", "generation-a"),
    ]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_ignores_duplicate_identity_within_one_result_list():
    duplicate = ranked("chunk", "generation")

    fused = reciprocal_rank_fusion([[duplicate, duplicate], [ranked("other", "generation")]])

    assert [(item.chunk_id, item.generation_id) for item in fused] == [
        ("chunk", "generation"),
        ("other", "generation"),
    ]
    assert fused[0].score == pytest.approx(1 / 61)


def test_rrf_rejects_non_positive_k():
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion([], k=0)
