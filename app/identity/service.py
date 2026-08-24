from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.identity.models import User
from app.identity.repository import get_user_by_id, get_user_by_username

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def authentication_error() -> AppError:
    return AppError("authentication_error", "Invalid credentials", 401)


def authenticate_user(session: Session, username: str, password: str) -> User:
    user = get_user_by_username(session, username)
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    try:
        password_matches = verify_password(password, password_hash)
    except (TypeError, ValueError):
        password_matches = False
    except Exception as exc:
        if exc.__class__.__module__.startswith("pwdlib"):
            password_matches = False
        else:
            raise
    if user is None or not password_matches or not user.is_active:
        raise authentication_error()
    return user


def create_access_token(user: User, secret: str) -> str:
    issued_at = datetime.now(UTC).replace(microsecond=0)
    payload = {
        "sub": user.id,
        "role": user.role.value,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def resolve_current_user(session: Session, token: str, secret: str) -> User:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "role", "iat", "exp"]},
        )
        user_id = payload["sub"]
        role = payload["role"]
        if not isinstance(user_id, str) or not isinstance(role, str):
            raise authentication_error()
        user = get_user_by_id(session, user_id)
        if user is None or not user.is_active or user.role.value != role:
            raise authentication_error()
        return user
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise authentication_error() from exc
