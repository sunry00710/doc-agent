"""全局角色的统一判断入口（多角色演进接缝）。

当前 User.role 是单一枚举；产品规划中「一人兼多角色」上线后，这里的实现会改为
读取 user.roles 集合，**调用点无需改动**——所有全局角色判断都必须经过本模块，
禁止在业务代码里直接比较 `user.role == Role.xxx`（见 docs/multi-role-migration.md）。

项目级角色（contributor/reviewer/owner）不走这里，见 app/projects/permissions.py。
"""
from __future__ import annotations

from app.identity.models import Role, User


def has_role(user: User, role: Role) -> bool:
    return user.role == role


def has_any_role(user: User, *roles: Role) -> bool:
    return user.role in roles


def is_admin(user: User) -> bool:
    return has_role(user, Role.admin)


def can_govern_knowledge(user: User) -> bool:
    """知识库晋升治理权（reviewer 与 admin 均可，见 promotion_service 的角色校验）。"""
    return has_any_role(user, Role.reviewer, Role.admin)
