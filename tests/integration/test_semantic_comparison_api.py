from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agent.messages import AssistantMessage
from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.identity.models import Role, User
from app.main import create_app
from app.projects.models import MembershipRole, Project, ProjectMember
from app.providers.fake import FakeProvider

SOURCE_A = "审计发现：某单位未按规定归档采购合同，涉及金额 30 万元。\n\n上述问题需限期整改。\n"
SOURCE_B = "审计发现：某单位未按规定妥善归档采购合同，涉及金额 45 万元。\n\n上述问题需限期整改。\n"

MODEL_CHANGES = {
    "changes": [
        {
            "category": "semantic_rewrite",
            "summary": "补语调整：归档要求表述更完整",
            "old_text": "未按规定归档采购合同",
            "new_text": "未按规定妥善归档采购合同",
            "impact": "意思未变，属于表述调整",
            "semantic_equivalent": True,
        },
        {
            "category": "data_change",
            "summary": "金额由 30 万元改为 45 万元",
            "old_text": "30 万元",
            "new_text": "45 万元",
            "impact": "金额变化需核对取证记录",
            "semantic_equivalent": False,
        },
    ]
}


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'comparison.db'}")
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
            jwt_secret="test-secret-at-least-thirty-two-bytes",
            storage_dir=tmp_path / "storage",
        )
    )

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", data={"username": username, "password": "correct"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_two_versions(client: TestClient, db_session: Session, username: str) -> tuple[dict[str, str], str, str]:
    user = User(username=username, password_hash=hash_password("correct"), role=Role.user)
    db_session.add(user)
    db_session.commit()
    project = Project(name="整改报告")
    db_session.add(project)
    db_session.flush()
    db_session.add(
        ProjectMember(project_id=project.id, user_id=user.id, membership_role=MembershipRole.owner)
    )
    db_session.commit()
    headers = auth_headers(client, username)
    document = client.post(
        "/api/documents",
        json={
            "project_id": project.id,
            "title": "整改报告",
            "domain": "finance",
            "document_type": "report",
        },
        headers=headers,
    ).json()
    versions = [
        client.post(
            f"/api/documents/{document['id']}/versions",
            files={"file": (f"v{index}.md", source.encode("utf-8"), "text/markdown")},
            headers=headers,
        ).json()
        for index, source in enumerate((SOURCE_A, SOURCE_B), start=1)
    ]
    return headers, versions[0]["id"], versions[1]["id"]


def compare(client: TestClient, headers: dict[str, str], version_a: str, version_b: str, mode: str = "semantic"):
    return client.post(
        "/api/quality/comparisons",
        json={"version_a_id": version_a, "version_b_id": version_b, "comparison_type": mode},
        headers=headers,
    )


def test_model_backed_comparison_returns_structured_semantic_changes(client, db_session):
    headers, version_a, version_b = seed_two_versions(client, db_session, "model-owner")
    provider = FakeProvider([AssistantMessage(content=json.dumps(MODEL_CHANGES, ensure_ascii=False))])
    client.app.state.agent_provider = provider

    response = compare(client, headers, version_a, version_b)

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "llm"
    assert body["degraded"] is False
    assert body["comparison_type"] == "semantic"
    assert [change["category"] for change in body["changes"]] == ["semantic_rewrite", "data_change"]
    assert body["changes"][0]["semantic_equivalent"] is True
    assert body["changes"][0]["old_text"] == "未按规定归档采购合同"
    # 版本绑定由后端强制，模型不能张冠李戴
    assert all(change["version_a_id"] == version_a for change in body["changes"])
    assert all(change["version_b_id"] == version_b for change in body["changes"])
    assert provider.requests[0].messages[0].role == "system"


def test_offline_demo_provider_reports_the_heuristic_engine(client, db_session):
    headers, version_a, version_b = seed_two_versions(client, db_session, "offline-owner")
    client.app.state.agent_provider = FakeProvider()

    response = compare(client, headers, version_a, version_b)

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "heuristic"
    assert body["degraded"] is False
    assert any(change["category"] == "data_change" for change in body["changes"])


def test_provider_failure_is_reported_as_a_degraded_line_diff(client, db_session):
    headers, version_a, version_b = seed_two_versions(client, db_session, "degraded-owner")
    client.app.state.agent_provider = None

    response = compare(client, headers, version_a, version_b)

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "difflib"
    assert body["degraded"] is True
    assert body["degraded_reason"] == "provider_not_configured"
    assert body["changes"]
