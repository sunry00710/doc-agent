from pathlib import Path
from uuid import UUID

import jwt
import pytest
from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import Role, User
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TEST_JWT_SECRET = "test-secret-at-least-thirty-two-bytes"


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        jwt_secret=TEST_JWT_SECRET,
    )
    app = create_app(settings)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_factory(db_session: Session):
    def create_user(
        *,
        username: str,
        password: str,
        role: str = "user",
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username.strip().lower(),
            password_hash=hash_password(password),
            role=Role(role),
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return create_user


def assert_authentication_error(response) -> None:
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "authentication_error"
    assert error["message"] == "Invalid credentials"
    assert error["retryable"] is False


def test_login_and_read_current_user(client: TestClient, user_factory):
    user_factory(username="writer", password="correct", role="user")

    login = client.post(
        "/api/auth/login",
        data={"username": "writer", "password": "correct"},
    )

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    token = login.json()["access_token"]
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "writer"
    assert me.json()["role"] == "user"
    assert me.json()["is_active"] is True
    UUID(me.json()["id"])

    claims = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == me.json()["id"]
    assert claims["role"] == "user"
    assert isinstance(claims["iat"], int)
    assert claims["exp"] - claims["iat"] == 30 * 60


def test_login_normalizes_username(client: TestClient, user_factory):
    user_factory(username="writer", password="correct")

    response = client.post(
        "/api/auth/login",
        data={"username": "  WRITER  ", "password": "correct"},
    )

    assert response.status_code == 200


def test_bad_password_returns_authentication_error(client: TestClient, user_factory):
    user_factory(username="writer", password="correct")

    response = client.post(
        "/api/auth/login",
        data={"username": "writer", "password": "wrong"},
    )

    assert_authentication_error(response)


def test_me_requires_bearer_token(client: TestClient):
    response = client.get("/api/auth/me")

    assert_authentication_error(response)


def test_me_rejects_invalid_token(client: TestClient):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert_authentication_error(response)


def test_inactive_user_cannot_log_in(client: TestClient, user_factory):
    user_factory(username="writer", password="correct", is_active=False)

    response = client.post(
        "/api/auth/login",
        data={"username": "writer", "password": "correct"},
    )

    assert_authentication_error(response)
