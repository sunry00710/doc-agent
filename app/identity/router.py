from typing import Annotated

from app.db.session import get_db
from app.identity.models import User
from app.identity.schemas import Token, UserRead
from app.identity.service import (
    authenticate_user,
    authentication_error,
    create_access_token,
    resolve_current_user,
)
from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if token is None:
        raise authentication_error()
    secret = request.app.state.settings.jwt_secret.get_secret_value()
    return resolve_current_user(session, token, secret)


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[Session, Depends(get_db)],
) -> Token:
    user = authenticate_user(session, form_data.username, form_data.password)
    secret = request.app.state.settings.jwt_secret.get_secret_value()
    return Token(access_token=create_access_token(user, secret))


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
