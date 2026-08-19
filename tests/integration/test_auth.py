from pathlib import Path
from uuid import UUID

import jwt
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import Role, User
from app.identity.repository import add_user
from app.identity.service import authenticate_user
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TEST_JWT_SECRET = "test-secret-at-least-thirty-two-bytes"


@pytest.fixture
def migrated_engine(tmp_path: Path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


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


def test_alembic_schema_enforces_role_check_and_normalized_uniqueness(migrated_engine):
    constraints = sa.inspect(migrated_engine).get_check_constraints("users")
    assert constraints == [
        {
            "name": "ck_users_role",
            "sqltext": "role IN ('user', 'reviewer', 'admin')",
        }
    ]

    with migrated_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, :role, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "1", "username": "writer", "password_hash": "hash", "role": "user"},
        )

    with (
        pytest.raises(sa.exc.IntegrityError),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, :role, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "2", "username": "WRITER", "password_hash": "hash", "role": "user"},
        )

    with (
        pytest.raises(sa.exc.IntegrityError),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, :role, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": "3", "username": "other", "password_hash": "hash", "role": "owner"},
        )


def test_create_app_uses_selected_database_without_dependency_override(tmp_path: Path):
    database_path = tmp_path / "selected.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="selected", password_hash=hash_password("correct")))
        session.commit()
    engine.dispose()

    app = create_app(
        Settings(environment="test", database_url=database_url, jwt_secret=TEST_JWT_SECRET)
    )
    with TestClient(app) as selected_client:
        response = selected_client.post(
            "/api/auth/login", data={"username": "selected", "password": "correct"}
        )

    assert response.status_code == 200


def test_direct_orm_write_normalizes_username_and_enforces_uniqueness(db_session: Session):
    db_session.add(User(username="  Writer  ", password_hash=hash_password("first")))
    db_session.commit()
    stored = db_session.scalar(sa.select(User))
    assert stored is not None
    assert stored.username == "writer"

    db_session.add(User(username="WRITER", password_hash=hash_password("second")))
    with pytest.raises(sa.exc.IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_role_check_constraint_rejects_unknown_role(db_session: Session):
    with pytest.raises(sa.exc.IntegrityError):
        db_session.execute(
            sa.text(
                "INSERT INTO users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, :role, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "username": "writer",
                "password_hash": hash_password("correct"),
                "role": "owner",
            },
        )
        db_session.commit()
    db_session.rollback()


def test_unknown_username_performs_dummy_password_verification(db_session: Session, monkeypatch):
    calls: list[tuple[str, str]] = []

    def observable_verify(password: str, password_hash: str) -> bool:
        calls.append((password, password_hash))
        return False

    monkeypatch.setattr("app.identity.service.verify_password", observable_verify)

    with pytest.raises(Exception) as caught:
        authenticate_user(db_session, "missing", "attempt")

    assert getattr(caught.value, "code", None) == "authentication_error"
    assert calls and calls[0][0] == "attempt"


def test_malformed_stored_password_hash_returns_authentication_error(client: TestClient, db_session: Session):
    db_session.add(User(username="broken", password_hash="not-a-supported-hash"))
    db_session.commit()

    response = client.post(
        "/api/auth/login", data={"username": "broken", "password": "attempt"}
    )

    assert_authentication_error(response)


def test_repository_add_user_does_not_commit_transaction(db_session: Session):
    user = User(username="pending", password_hash=hash_password("correct"))

    add_user(db_session, user)

    assert user.id is not None
    assert db_session.in_transaction()
    db_session.rollback()
    db_session.expire_all()
    assert db_session.scalar(sa.select(User).where(User.username == "pending")) is None


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
