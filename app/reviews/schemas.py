from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID
    expected_revision: int = Field(ge=0, default=0)


class ReviewAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: UUID
    expected_revision: int = Field(ge=0)


class ReviewTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str
    expected_revision: int = Field(ge=0)


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_range: dict[str, int] = Field(min_length=2)
    text: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class ResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_version_id: UUID
    assessment: str
    expected_revision: int = Field(ge=0)


class ResponseConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    version_id: UUID
    state: str
    reviewer_id: UUID | None
    workflow_revision: int


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    review_id: UUID
    version_id: UUID
    source_range: dict[str, int]
    text: str
    status: str
    created_by: UUID


class ResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    comment_id: UUID
    response_version_id: UUID
    assessment: str
    reviewer_confirmed: bool
