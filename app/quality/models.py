from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WritingContract(Base):
    __tablename__ = "writing_contracts"
    __table_args__ = (
        UniqueConstraint("document_id", name="writing_contract_document"),
        CheckConstraint("active_revision > 0", name="positive_contract_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    active_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class WritingContractRevision(Base):
    __tablename__ = "writing_contract_revisions"
    __table_args__ = (
        UniqueConstraint("contract_id", "revision", name="contract_revision_number"),
        CheckConstraint("revision > 0", name="positive_contract_revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(ForeignKey("writing_contracts.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_organization: Mapped[str] = mapped_column(String(255), nullable=False)
    reporting_period: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    standard_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    precedent_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
