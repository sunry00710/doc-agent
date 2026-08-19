from datetime import datetime, timedelta, timezone

import jwt
from app.core.errors import AppError
from app.core.security import verify_password
from app.identity.models import User
from app.identity.repository import get_user_by_id, get_user_by_username
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def authentication_error() -> AppError:
    return AppError("authentication_error", "Invalid credentials", 401)


def authenticate_user(session: Session, username: str, password: str) -> User:
    user = get_user_by_username(session, username)
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        raise authentication_error()
    return user


def create_access_token(user: User, secret: str) -> str:
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)
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
