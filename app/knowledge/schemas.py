from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IngestionJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    payload_version: int = 1
    version_id: UUID
    space_id: UUID


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
