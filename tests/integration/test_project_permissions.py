from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import Role, User
from app.main import create_app
from app.projects.models import MembershipRole, ProjectMember
from app.projects.permissions import ProjectAction, require_project_permission
from app.projects.service import add_project_member
from app.projects.service import create_project as create_project_service

TEST_JWT_SECRET = "test-secret-at-least-thirty-two-bytes"


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    app = create_app(
        Settings(environment="test", database_url="sqlite://", jwt_secret=TEST_JWT_SECRET)
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_factory(db_session: Session):
    def create_user(username: str, role: Role = Role.user) -> User:
        user = User(username=username, password_hash=hash_password("correct"), role=role)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return create_user


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", data={"username": username, "password": "correct"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_project(client: TestClient, owner: User, name: str = "Annual report") -> dict:
    response = client.post(
        "/api/projects", json={"name": name}, headers=auth_headers(client, owner.username)
    )
    assert response.status_code == 201
    return response.json()


def assert_safe_error(response, status_code: int, code: str, message: str) -> None:
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    assert response.json()["error"]["retryable"] is False


def test_owner_creation_is_atomic_and_owner_can_list_project(client, db_session, user_factory):
    owner = user_factory("owner")

    project = create_project(client, owner)

    UUID(project["id"])
    assert project["name"] == "Annual report"
    membership = db_session.scalar(
        sa.select(ProjectMember).where(ProjectMember.project_id == project["id"])
    )
    assert membership is not None
    assert membership.user_id == owner.id
    assert membership.membership_role is MembershipRole.owner
    listed = client.get("/api/projects", headers=auth_headers(client, owner.username))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project["id"]]


def test_project_name_rejects_whitespace_only_value(client, user_factory):
    owner = user_factory("owner")

    response = client.post(
        "/api/projects", json={"name": "   "}, headers=auth_headers(client, owner.username)
    )

    assert_safe_error(response, 422, "validation_error", "Request validation failed")


def test_contributor_can_access_project_but_non_member_cannot(client, user_factory):
    owner = user_factory("owner")
    contributor = user_factory("contributor")
    outsider = user_factory("outsider")
    project = create_project(client, owner)

    added = client.post(
        f"/api/projects/{project['id']}/members",
        json={"user_id": contributor.id, "membership_role": "contributor"},
        headers=auth_headers(client, owner.username),
    )

    assert added.status_code == 201
    assert added.json()["membership_role"] == "contributor"
    assert client.get(
        f"/api/projects/{project['id']}/members",
        headers=auth_headers(client, contributor.username),
    ).status_code == 200
    denied = client.get(
        f"/api/projects/{project['id']}/members",
        headers=auth_headers(client, outsider.username),
    )
    assert_safe_error(denied, 403, "permission_denied", "Project access denied")


def test_reviewer_membership_grants_review_but_global_reviewer_role_does_not(
    client, db_session, user_factory
):
    owner = user_factory("owner")
    member_reviewer = user_factory("member-reviewer")
    global_reviewer = user_factory("global-reviewer", Role.reviewer)
    project = create_project(client, owner)
    response = client.post(
        f"/api/projects/{project['id']}/members",
        json={"user_id": member_reviewer.id, "membership_role": "reviewer"},
        headers=auth_headers(client, owner.username),
    )
    assert response.status_code == 201

    allowed = require_project_permission(
        UUID(project["id"]), ProjectAction.review, member_reviewer, db_session
    )
    assert allowed.id == project["id"]
    with pytest.raises(AppError, match="Project access denied") as caught:
        require_project_permission(
            UUID(project["id"]), ProjectAction.view, global_reviewer, db_session
        )
    assert caught.value.code == "permission_denied"
    assert caught.value.status_code == 403


@pytest.mark.parametrize(
    ("membership_role", "allowed_actions"),
    [
        (MembershipRole.contributor, {"view", "edit", "comment", "submit"}),
        (MembershipRole.reviewer, {"view", "edit", "comment", "submit", "review"}),
        (
            MembershipRole.owner,
            {"view", "edit", "comment", "submit", "review", "manage_members"},
        ),
    ],
)
def test_explicit_permission_matrix_covers_every_project_action(
    client, db_session, user_factory, membership_role, allowed_actions
):
    owner = user_factory(f"owner-{membership_role.value}")
    member = owner
    project = create_project(client, owner, membership_role.value)
    if membership_role is not MembershipRole.owner:
        member = user_factory(f"member-{membership_role.value}")
        response = client.post(
            f"/api/projects/{project['id']}/members",
            json={"user_id": member.id, "membership_role": membership_role.value},
            headers=auth_headers(client, owner.username),
        )
        assert response.status_code == 201

    assert {action.value for action in ProjectAction} == {
        "view",
        "edit",
        "comment",
        "submit",
        "review",
        "manage_members",
    }
    for action in ProjectAction:
        if action.value in allowed_actions:
            assert require_project_permission(UUID(project["id"]), action, member, db_session)
        else:
            with pytest.raises(AppError) as caught:
                require_project_permission(UUID(project["id"]), action, member, db_session)
            assert caught.value.code == "permission_denied"


def test_only_owner_can_add_members_and_duplicate_membership_is_rejected(
    client, user_factory
):
    owner = user_factory("owner")
    contributor = user_factory("contributor")
    target = user_factory("target")
    project = create_project(client, owner)
    endpoint = f"/api/projects/{project['id']}/members"
    first = client.post(
        endpoint,
        json={"user_id": contributor.id, "membership_role": "contributor"},
        headers=auth_headers(client, owner.username),
    )
    assert first.status_code == 201

    forbidden = client.post(
        endpoint,
        json={"user_id": target.id, "membership_role": "reviewer"},
        headers=auth_headers(client, contributor.username),
    )
    assert_safe_error(forbidden, 403, "permission_denied", "Project access denied")
    duplicate = client.post(
        endpoint,
        json={"user_id": contributor.id, "membership_role": "reviewer"},
        headers=auth_headers(client, owner.username),
    )
    assert_safe_error(duplicate, 409, "membership_exists", "Project membership already exists")


def test_member_lists_are_project_scoped(client, user_factory):
    first_owner = user_factory("first-owner")
    second_owner = user_factory("second-owner")
    first_member = user_factory("first-member")
    second_member = user_factory("second-member")
    first = create_project(client, first_owner, "First")
    second = create_project(client, second_owner, "Second")
    for project, owner, member in (
        (first, first_owner, first_member),
        (second, second_owner, second_member),
    ):
        response = client.post(
            f"/api/projects/{project['id']}/members",
            json={"user_id": member.id, "membership_role": "contributor"},
            headers=auth_headers(client, owner.username),
        )
        assert response.status_code == 201

    members = client.get(
        f"/api/projects/{first['id']}/members",
        headers=auth_headers(client, first_owner.username),
    )
    assert members.status_code == 200
    assert {member["user_id"] for member in members.json()} == {
        first_owner.id,
        first_member.id,
    }
    assert second_owner.id not in {member["user_id"] for member in members.json()}
    assert second_member.id not in {member["user_id"] for member in members.json()}


def test_unknown_project_and_user_return_safe_not_found(client, user_factory):
    owner = user_factory("owner")
    project = create_project(client, owner)
    headers = auth_headers(client, owner.username)

    missing_project = client.get(
        "/api/projects/00000000-0000-0000-0000-000000000000/members", headers=headers
    )
    assert_safe_error(missing_project, 404, "not_found", "Project not found")
    missing_user = client.post(
        f"/api/projects/{project['id']}/members",
        json={
            "user_id": "00000000-0000-0000-0000-000000000000",
            "membership_role": "contributor",
        },
        headers=headers,
    )
    assert_safe_error(missing_user, 404, "not_found", "User not found")


def test_project_services_leave_transaction_ownership_to_caller(db_session, user_factory):
    owner = user_factory("service-owner")
    target = user_factory("service-target")

    project = create_project_service(db_session, "Composable", owner)
    add_project_member(
        db_session,
        UUID(project.id),
        UUID(target.id),
        MembershipRole.contributor,
        owner,
    )

    assert db_session.in_transaction()
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(type(project), project.id) is None


def test_alembic_project_schema_enforces_roles_uniqueness_and_foreign_keys(
    tmp_path: Path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = sa.inspect(engine)

    assert {table for table in inspector.get_table_names()} >= {
        "users",
        "projects",
        "project_members",
    }
    constraints = inspector.get_check_constraints("project_members")
    assert constraints == [
        {
            "name": "ck_project_members_membership_role",
            "sqltext": "membership_role IN ('contributor', 'reviewer', 'owner')",
        }
    ]
    unique_constraints = inspector.get_unique_constraints("project_members")
    assert any(constraint["column_names"] == ["project_id", "user_id"] for constraint in unique_constraints)
    engine.dispose()
