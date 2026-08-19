from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.documents.models import DocumentVersion
from app.documents.service import create_version
from app.identity.models import Role, User
from app.main import create_app
from app.projects.models import MembershipRole, Project, ProjectMember

TEST_JWT_SECRET = "test-secret-at-least-thirty-two-bytes"


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'documents.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db_session: Session, tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite://",
            jwt_secret=TEST_JWT_SECRET,
            storage_dir=tmp_path / "storage",
            max_upload_bytes=64,
        )
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


def user_factory(session: Session, username: str, role: Role = Role.user) -> User:
    user = User(username=username, password_hash=hash_password("correct"), role=role)
    session.add(user)
    session.commit()
    return user


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", data={"username": username, "password": "correct"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def project_for(session: Session, owner: User) -> Project:
    project = Project(name="Annual report")
    session.add(project)
    session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner
        )
    )
    session.commit()
    return project


def assert_safe_error(response, status_code: int, code: str, message: str) -> None:
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message


def test_create_upload_list_and_read_immutable_version(client: TestClient, db_session: Session):
    owner = user_factory(db_session, "owner")
    project = project_for(db_session, owner)
    headers = auth_headers(client, owner.username)

    created = client.post(
        "/api/documents",
        json={
            "project_id": project.id,
            "title": "Annual report",
            "domain": "finance",
            "document_type": "report",
        },
        headers=headers,
    )
    assert created.status_code == 201
    document = created.json()
    UUID(document["id"])
    assert document["owner_id"] == owner.id
    assert document["status"] == "draft"

    upload = client.post(
        f"/api/documents/{document['id']}/versions",
        files={"file": ("../../untrusted.md", b"one\r\ntwo\r", "text/markdown")},
        headers=headers,
    )
    assert upload.status_code == 201
    version = upload.json()
    assert version["number"] == 1
    assert version["content_sha256"] == "c3f9c8c283a2b1f2f1896f27a01cbe3cddc0c9d93f752e4639035a0f5b36f6e8"
    assert "untrusted" not in version["storage_key"]

    listed = client.get(f"/api/documents/{document['id']}/versions", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == version["id"]
    assert listed.json()[0]["number"] == version["number"]
    content = client.get(
        f"/api/documents/{document['id']}/versions/{version['number']}", headers=headers
    )
    assert content.status_code == 200
    assert content.content == b"one\ntwo\n"


def test_document_access_requires_project_membership(client: TestClient, db_session: Session):
    owner = user_factory(db_session, "owner")
    outsider = user_factory(db_session, "outsider", Role.reviewer)
    project = project_for(db_session, owner)
    owner_headers = auth_headers(client, owner.username)
    document = client.post(
        "/api/documents",
        json={"project_id": project.id, "title": "Private", "domain": "finance", "document_type": "report"},
        headers=owner_headers,
    ).json()

    denied = client.get(
        f"/api/documents/{document['id']}/versions", headers=auth_headers(client, outsider.username)
    )
    assert_safe_error(denied, 403, "permission_denied", "Project access denied")


def test_upload_validation_and_missing_document_are_safe(client: TestClient, db_session: Session):
    owner = user_factory(db_session, "owner")
    headers = auth_headers(client, owner.username)
    missing = "00000000-0000-0000-0000-000000000000"

    response = client.post(
        f"/api/documents/{missing}/versions",
        files={"file": ("draft.md", b"draft", "text/markdown")},
        headers=headers,
    )
    assert_safe_error(response, 404, "not_found", "Document not found")

    project = project_for(db_session, owner)
    document = client.post(
        "/api/documents",
        json={"project_id": project.id, "title": "Validation", "domain": "finance", "document_type": "report"},
        headers=headers,
    ).json()
    invalid = client.post(
        f"/api/documents/{document['id']}/versions",
        files={"file": ("draft.pdf", b"draft", "application/pdf")},
        headers=headers,
    )
    assert_safe_error(invalid, 422, "validation_error", "Invalid document upload")
    too_large = client.post(
        f"/api/documents/{document['id']}/versions",
        files={"file": ("draft.md", b"x" * 65, "text/markdown")},
        headers=headers,
    )
    assert_safe_error(too_large, 422, "validation_error", "Invalid document upload")


def test_versions_are_monotonic_and_immutable_at_orm_and_database_boundaries(
    db_session: Session, tmp_path: Path
):
    owner = user_factory(db_session, "owner")
    project = project_for(db_session, owner)
    from app.documents.service import create_document
    from app.documents.storage import FileStorage

    document = create_document(db_session, project.id, "Immutable", "finance", "report", owner)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    first = create_version(db_session, storage, UUID(document.id), b"same\r\n", owner)
    second = create_version(db_session, storage, UUID(document.id), b"same\n", owner)
    db_session.commit()
    assert (first.number, second.number) == (1, 2)
    assert first.content_sha256 == second.content_sha256

    first.storage_key = "changed"
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()
    db_session.rollback()
    assert db_session.get(DocumentVersion, first.id).storage_key != "changed"
