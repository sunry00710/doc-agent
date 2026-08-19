from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    title: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=255)

    @field_validator("title", "domain", "document_type")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value.strip()


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    owner_id: UUID
    title: str
    domain: str
    document_type: str
    status: str


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    number: int
    content_sha256: str
    storage_key: str
    created_by: UUID
    created_at: datetime
