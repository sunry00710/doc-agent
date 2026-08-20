from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankedId:
    chunk_id: str
    generation_id: str
    score: float


def reciprocal_rank_fusion(result_lists: list[list[RankedId]], k: int = 60) -> list[RankedId]:
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[tuple[str, str], float] = {}
    first_seen: dict[tuple[str, str], int] = {}
    order = 0
    for results in result_lists:
        seen: set[tuple[str, str]] = set()
        for rank, item in enumerate(results, start=1):
            identity = (item.chunk_id, item.generation_id)
            if identity in seen:
                continue
            seen.add(identity)
            if identity not in first_seen:
                first_seen[identity] = order
                order += 1
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (k + rank)
    ranked = sorted(scores, key=lambda identity: (-scores[identity], first_seen[identity], identity))
    return [RankedId(chunk_id=identity[0], generation_id=identity[1], score=scores[identity]) for identity in ranked]
