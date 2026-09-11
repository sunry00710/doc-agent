from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import Role, User
from app.main import create_app

TEST_JWT_SECRET = "test-secret-at-least-thirty-two-bytes"


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'admin.db'}")
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
    def create_user(*, username: str, password: str = "correct", role: str = "user", is_active: bool = True) -> User:
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


def auth_headers(client: TestClient, username: str, password: str = "correct") -> dict[str, str]:
    login = client.post("/api/auth/login", data={"username": username, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_admin_lists_users_with_roles(client: TestClient, user_factory):
    user_factory(username="root", role="admin")
    user_factory(username="lead", role="reviewer")
    user_factory(username="staff", role="user")

    response = client.get("/api/admin/users", headers=auth_headers(client, "root"))

    assert response.status_code == 200
    body = response.json()
    assert [item["username"] for item in body] == ["root", "lead", "staff"]
    assert [item["role"] for item in body] == ["admin", "reviewer", "user"]
    assert all({"id", "username", "role", "is_active"} <= set(item) for item in body)


def test_non_admin_cannot_list_or_update_users(client: TestClient, user_factory):
    reviewer = user_factory(username="lead", role="reviewer")
    user_factory(username="staff", role="user")
    headers = auth_headers(client, "lead")

    listing = client.get("/api/admin/users", headers=headers)
    update = client.patch(f"/api/admin/users/{reviewer.id}", json={"role": "admin"}, headers=headers)

    assert listing.status_code == 403
    assert listing.json()["error"]["code"] == "permission_denied"
    assert update.status_code == 403


def test_admin_promotes_and_deactivates_a_user(client: TestClient, user_factory):
    user_factory(username="root", role="admin")
    target = user_factory(username="staff", role="user")
    headers = auth_headers(client, "root")

    promoted = client.patch(f"/api/admin/users/{target.id}", json={"role": "reviewer"}, headers=headers)
    deactivated = client.patch(f"/api/admin/users/{target.id}", json={"is_active": False}, headers=headers)

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "reviewer"
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_deactivated_user_cannot_log_in(client: TestClient, user_factory):
    user_factory(username="root", role="admin")
    target = user_factory(username="staff", role="user")

    client.patch(
        f"/api/admin/users/{target.id}",
        json={"is_active": False},
        headers=auth_headers(client, "root"),
    )

    response = client.post("/api/auth/login", data={"username": "staff", "password": "correct"})
    assert response.status_code == 401


def test_admin_cannot_demote_self(client: TestClient, user_factory):
    root = user_factory(username="root", role="admin")
    headers = auth_headers(client, "root")

    response = client.patch(f"/api/admin/users/{root.id}", json={"role": "user"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_last_admin_deactivation_is_rejected(client: TestClient, user_factory):
    root = user_factory(username="root", role="admin")
    other = user_factory(username="other", role="admin")
    headers = auth_headers(client, "root")

    client.patch(f"/api/admin/users/{other.id}", json={"is_active": False}, headers=headers)
    response = client.patch(f"/api/admin/users/{root.id}", json={"is_active": False}, headers=headers)

    assert response.status_code == 409


def test_patch_requires_known_user_and_payload(client: TestClient, user_factory):
    user_factory(username="root", role="admin")
    headers = auth_headers(client, "root")

    missing = client.patch("/api/admin/users/does-not-exist", json={"role": "user"}, headers=headers)
    empty = client.patch(
        f"/api/admin/users/{user_factory(username='staff').id}", json={}, headers=headers
    )

    assert missing.status_code == 404
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "validation_error"
