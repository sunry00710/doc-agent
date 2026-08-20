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


class Citation(SearchHit):
    pass
