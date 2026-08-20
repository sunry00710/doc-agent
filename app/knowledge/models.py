from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeSpaceKind(str, Enum):
    personal = "personal"
    project = "project"
    shared = "shared"
    standard = "standard"


class KnowledgeState(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    indexed = "indexed"
    archived = "archived"


class GenerationState(str, Enum):
    building = "building"
    active = "active"
    failed = "failed"


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        CheckConstraint("kind IN ('personal', 'project', 'shared', 'standard')", name="knowledge_space_kind"),
        CheckConstraint("(kind = 'personal' AND owner_id IS NOT NULL AND project_id IS NULL) OR (kind = 'project' AND project_id IS NOT NULL AND owner_id IS NULL) OR (kind IN ('shared', 'standard') AND owner_id IS NULL AND project_id IS NULL)", name="valid_scope"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[KnowledgeSpaceKind] = mapped_column(SqlEnum(KnowledgeSpaceKind, native_enum=False, create_constraint=False), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("version_id", "space_id", name="version_space"),
        ForeignKeyConstraint(
            ["active_generation_id", "id"],
            ["knowledge_generations.id", "knowledge_generations.knowledge_document_id"],
            name="active_generation_belongs_to_document",
        ),
        CheckConstraint("state IN ('pending_review', 'approved', 'indexed', 'archived')", name="knowledge_document_state"),
        CheckConstraint("authority_level >= 0", name="nonnegative_authority"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[KnowledgeState] = mapped_column(SqlEnum(KnowledgeState, native_enum=False, create_constraint=False), nullable=False, default=KnowledgeState.indexed)
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    active_generation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class KnowledgeGeneration(Base):
    __tablename__ = "knowledge_generations"
    __table_args__ = (
        UniqueConstraint("id", "knowledge_document_id", name="generation_document_pair"),
        CheckConstraint("state IN ('building', 'active', 'failed')", name="knowledge_generation_state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    knowledge_document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[GenerationState] = mapped_column(SqlEnum(GenerationState, native_enum=False, create_constraint=False), nullable=False, default=GenerationState.building)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        PrimaryKeyConstraint("id", "generation_id", name="knowledge_chunk_generation_pk"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="valid_chunk_offsets"),
        Index("ix_knowledge_chunks_generation_version", "generation_id", "version_id"),
    )
    id: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_id: Mapped[str] = mapped_column(ForeignKey("knowledge_generations.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    heading_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
