from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PromotionStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"
    revoked = "revoked"


class PromotionRequest(Base):
    __tablename__ = "promotion_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review','approved','rejected','indexing','indexed','failed','revoked')",
            name="promotion_status",
        ),
        CheckConstraint("authority_level >= 0", name="promotion_authority_nonnegative"),
        CheckConstraint(
            "quality_status IN ('passed','failed','needs_human_review')",
            name="promotion_quality_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_space_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_spaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[PromotionStatus] = mapped_column(
        String(32), nullable=False, default=PromotionStatus.pending_review
    )
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    findings: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="promotion-v1"
    )
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    public_authority: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
