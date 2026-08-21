from __future__ import annotations

from app.quality.check import normalize_quality_response
from app.quality.schemas import QualityResponse


def judge_document(source: str, response: QualityResponse) -> QualityResponse:
    return normalize_quality_response(source, response)
