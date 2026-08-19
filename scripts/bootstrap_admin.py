from __future__ import annotations

import argparse
from getpass import getpass

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_database_engine
from app.identity.models import Role, User
from app.identity.repository import add_user, get_user_by_username, normalize_username
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the initial local administrator account.")
    parser.add_argument("--username", required=True)
    return parser.parse_args()


def bootstrap_admin(session: Session, username: str, password: str) -> User:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Username must not be empty")
    if get_user_by_username(session, normalized_username) is not None:
        raise ValueError("Username already exists")
    user = User(
        username=normalized_username,
        password_hash=hash_password(password),
        role=Role.admin,
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

    engine = create_database_engine(Settings().database_url)
    try:
        with Session(engine) as session:
            try:
                user = bootstrap_admin(session, args.username, password)
            except ValueError as exc:
                print(str(exc))
                return 1
        print(f"Created administrator {user.username}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
