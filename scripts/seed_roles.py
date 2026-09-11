"""补齐三角色演示账号（管理员 / 上级 / 下级），幂等可重复执行。

前置：先跑过 scripts/seed_demo.py（提供演示项目「演示项目：年度审计报告」）。

- demo    / DemoPass-2026!  （管理员，seed_demo 已建；不存在时本脚本补建）
- shangji / ReviewPass-2026!  （上级：全局 reviewer + 项目 reviewer）
- xiashu  / StaffPass-2026!  （下级：全局 user + 项目 contributor）

只补齐缺失对象，已存在的跳过；不会修改已有账号的密码。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python scripts/<name>.py` 直接运行（补齐项目根到模块搜索路径）
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_database_engine
from app.identity.models import Role, User
from app.identity.repository import get_user_by_username, normalize_username
from app.projects.models import MembershipRole, Project, ProjectMember

DEMO_PROJECT_NAME = "演示项目：年度审计报告"

ACCOUNTS: list[tuple[str, str, Role, MembershipRole]] = [
    ("demo", "DemoPass-2026!", Role.admin, MembershipRole.owner),
    ("shangji", "ReviewPass-2026!", Role.reviewer, MembershipRole.reviewer),
    ("xiashu", "StaffPass-2026!", Role.user, MembershipRole.contributor),
]


def _ensure_user(session: Session, username: str, password: str, role: Role) -> tuple[User, bool]:
    existing = get_user_by_username(session, username)
    if existing is not None:
        return existing, False
    user = User(username=normalize_username(username), password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user, True


def _ensure_membership(session: Session, project_id: str, user_id: str, role: MembershipRole) -> bool:
    existing = session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    if existing is not None:
        return False
    session.add(ProjectMember(project_id=project_id, user_id=user_id, membership_role=role))
    session.flush()
    return True


def seed_roles(session: Session) -> list[tuple[str, Role, str]]:
    project = session.scalar(select(Project).where(Project.name == DEMO_PROJECT_NAME))
    if project is None:
        raise SystemExit(
            f"演示项目不存在（{DEMO_PROJECT_NAME}）。请先运行: uv run python scripts/seed_demo.py"
        )
    summary: list[tuple[str, Role, str]] = []
    for username, password, role, membership_role in ACCOUNTS:
        user, created = _ensure_user(session, username, password, role)
        joined = _ensure_membership(session, project.id, user.id, membership_role)
        state = "新建" if created else "已存在"
        member_state = "已加入项目" if joined else "已在项目中"
        summary.append((username, role, f"{state} / {member_state}"))
    return summary


def main() -> int:
    engine = create_database_engine(Settings().database_url)
    try:
        with Session(engine) as session:
            summary = seed_roles(session)
            session.commit()
        print("三角色演示账号就绪：")
        for username, role, state in summary:
            print(f"  - {username:<10} {role.value:<9} {state}")
        print("\n密码见 scripts/seed_roles.py 顶部常量；演示用，部署前必须更换。")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
