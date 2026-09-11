from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.identity.models import Role, User
from app.identity.roles import is_admin
from app.identity.router import get_current_user
from app.identity.schemas import UserRead

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None


def _require_admin(actor: User) -> None:
    if not is_admin(actor):
        raise AppError("permission_denied", "Administrator access required", 403)


def _active_admin_count(session: Session) -> int:
    # SQL 层计数（多角色迁移时改为对 user_roles 计数，见 docs/multi-role-migration.md §三）
    return session.scalar(
        select(func.count()).select_from(User).where(User.role == Role.admin, User.is_active.is_(True))
    ) or 0


def update_user(session: Session, target: User, data: UserUpdate, actor: User) -> User:
    if data.role is None and data.is_active is None:
        raise AppError("validation_error", "Nothing to update", 422)
    loses_admin = is_admin(target) and (
        (data.role is not None and data.role != Role.admin) or data.is_active is False
    )
    if target.id == actor.id and loses_admin:
        raise AppError("conflict", "Administrators cannot demote or deactivate themselves", 409)
    if loses_admin and _active_admin_count(session) <= 1:
        raise AppError("conflict", "The last active administrator cannot be demoted or deactivated", 409)
    if data.role is not None:
        target.role = data.role
    if data.is_active is not None:
        target.is_active = data.is_active
    session.flush()
    return target


@router.get("/users", response_model=list[UserRead])
def list_users(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    _require_admin(current_user)
    return list(session.scalars(select(User).order_by(User.created_at, User.username)))


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    data: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    _require_admin(current_user)
    target = session.get(User, user_id)
    if target is None:
        raise AppError("not_found", "User not found", 404)
    user = update_user(session, target, data, current_user)
    session.commit()
    return user
