from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models import User


def normalize_username(username: str) -> str:
    return username.strip().lower()


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    statement = select(User).where(User.username == normalize_username(username))
    return session.scalar(statement)


def add_user(session: Session, user: User) -> User:
    session.add(user)
    session.flush()
    return user
