from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from app.db.base import Base
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, event, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column


class Role(str, Enum):
    user = "user"
    reviewer = "reviewer"
    admin = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'reviewer', 'admin')", name="role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[Role] = mapped_column(
        SqlEnum(
            Role,
            name="role",
            native_enum=False,
            validate_strings=True,
            create_constraint=False,
        ),
        nullable=False,
        default=Role.user,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


Index("uq_users_username_normalized", func.lower(func.trim(User.username)), unique=True)


@event.listens_for(User.username, "set", retval=True)
def normalize_user_username(_target: User, value: str, _old_value: str, _initiator: object) -> str:
    return value.strip().lower()
