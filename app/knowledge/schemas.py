from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestionJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    payload_version: Literal[1] = 1
    version_id: UUID
    space_id: UUID

    @field_validator("version_id", "space_id", mode="before")
    @classmethod
    def parse_json_uuid(cls, value: object) -> object:
        if isinstance(value, str):
            return UUID(value)
        return value


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    mode: Literal["keyword", "dense", "hybrid"] = "keyword"


class SearchHit(BaseModel):
    model_config = ConfigDict(strict=True)
    chunk_id: str
    document_id: UUID
    version_id: UUID
    title: str
    heading_path: tuple[str, ...]
    quote: str
    start_offset: int
    end_offset: int


class KnowledgeSpaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    owner_id: UUID | None
    project_id: UUID | None


class KnowledgeSpaceList(BaseModel):
    items: list[KnowledgeSpaceRead]


class SpaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["personal"] = "personal"


class SpaceIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID


class IngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    space_id: UUID
    version_id: UUID
    state: str


from app.knowledge.promotion_schemas import PromotionRead


class PromotionList(BaseModel):
    items: list[PromotionRead]


class Citation(SearchHit):
    pass
