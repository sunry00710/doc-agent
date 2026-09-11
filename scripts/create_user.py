"""创建本地账号（管理员 / 上级 / 下级）。

用法示例：
    uv run python scripts/create_user.py --username shangji --role reviewer
    uv run python scripts/create_user.py --username xiashu --role user

密码不通过命令行传递（避免进入历史记录），运行时交互输入。
"""
from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

# 允许 `python scripts/create_user.py` 直接运行（脚本目录不在包路径里时补齐项目根）
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_database_engine
from app.identity.models import Role, User
from app.identity.repository import add_user, get_user_by_username, normalize_username

ROLE_HELP = {
    Role.admin: "管理员：管理用户与项目成员、评审、知识库治理",
    Role.reviewer: "上级：审核与批准下属提交、发起晋升治理",
    Role.user: "下级（员工）：编辑提交、评论、向知识库投稿",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a local Doc Agent account.")
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--role",
        choices=[role.value for role in Role],
        default=Role.user.value,
        help="; ".join(f"{role.value}={ROLE_HELP[role]}" for role in Role),
    )
    return parser.parse_args()


def create_user(session: Session, username: str, password: str, role: Role) -> User:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Username must not be empty")
    if get_user_by_username(session, normalized_username) is not None:
        raise ValueError("Username already exists")
    user = User(
        username=normalized_username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    try:
        user = add_user(session, user)
        session.commit()
        session.refresh(user)
        return user
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("Username already exists") from exc


def main() -> int:
    args = parse_args()
    password = getpass("Password: ")
    if not password:
        print("Password must not be empty")
        return 1
    confirm = getpass("Confirm password: ")
    if confirm != password:
        print("Passwords do not match")
        return 1

    engine = create_database_engine(Settings().database_url)
    try:
        with Session(engine) as session:
            try:
                user = create_user(session, args.username, password, Role(args.role))
            except ValueError as exc:
                print(str(exc))
                return 1
        print(f"Created {user.role.value} account: {user.username}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
