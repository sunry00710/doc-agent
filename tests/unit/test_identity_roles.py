"""全局角色判断入口的契约测试（多角色迁移接缝）。"""
from __future__ import annotations

from app.identity.models import Role, User
from app.identity.roles import can_govern_knowledge, has_any_role, has_role, is_admin


def make_user(role: Role) -> User:
    return User(username=f"u-{role.value}", password_hash="hash", role=role)


def test_role_helpers_match_single_role_assignment():
    admin, reviewer, staff = make_user(Role.admin), make_user(Role.reviewer), make_user(Role.user)

    assert is_admin(admin) and not is_admin(reviewer) and not is_admin(staff)
    assert has_role(reviewer, Role.reviewer)
    assert has_any_role(reviewer, Role.reviewer, Role.admin)
    assert not has_any_role(staff, Role.reviewer, Role.admin)


def test_governance_requires_reviewer_or_admin():
    assert can_govern_knowledge(make_user(Role.admin))
    assert can_govern_knowledge(make_user(Role.reviewer))
    assert not can_govern_knowledge(make_user(Role.user))
