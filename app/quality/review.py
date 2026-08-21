from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReviewSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1)
    suggestions: list[str] = Field(default_factory=list)
    pending_confirmation: list[str] = Field(default_factory=list)


def review_comments(review: ReviewSuggestion) -> ReviewSuggestion:
    return review
