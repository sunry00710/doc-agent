"""质量工具必须读取会话绑定的文档版本正文，而不是模型自填的 source。

背景（断链修复）：document_version_id 曾被存进 AgentContext 但无任何消费点，
模型可以传入与绑定版本文档无关的 source 骗过 check/judge。本测试锁定修复后的行为。
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.projects.models import MembershipRole, Project, ProjectMember
from app.quality.schemas import Finding, FindingSummary, QualityResponse
from app.quality.tools import FindingInput, QualityInput, _resolve_source


def _empty_response() -> QualityResponse:
    return QualityResponse(findings=[], summary=FindingSummary(total=0, low=0, medium=0, high=0), coverage=1)


class _Context:
    def __init__(self, *, document_version_id=None, session=None, actor=None, storage=None):
        self.document_version_id = document_version_id
        self.session = session
        self.actor = actor
        self.storage = storage


@pytest.fixture
def env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quality-bound.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))

    actor = User(username="author", password_hash="x", role=Role.user)
    session.add(actor)
    session.flush()
    project = Project(name="P")
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=actor.id, membership_role=MembershipRole.owner))
    stored = storage.store("bound.md", b"# Bound\n\nbound version content with needle")
    document = Document(project_id=project.id, owner_id=actor.id, title="Bound doc", domain="audit", document_type="report", status="draft")
    session.add(document)
    session.flush()
    version = DocumentVersion(document_id=document.id, number=1, content_sha256=stored.content_sha256, storage_key=stored.storage_key, created_by=actor.id)
    session.add(version)
    session.flush()
    yield session, storage, actor, version
    session.close()
    engine.dispose()


def test_resolve_source_prefers_bound_version(env) -> None:
    session, storage, actor, version = env
    context = _Context(document_version_id=UUID(version.id), session=session, actor=actor, storage=storage)
    # 模型自填的 source 与绑定版本不同 —— 必须用绑定版本的正文
    resolved = _resolve_source("attacker controlled text", context)
    assert "needle" in resolved
    assert "attacker" not in resolved


def test_resolve_source_falls_back_without_binding(env) -> None:
    session, storage, actor, _ = env
    context = _Context(session=session, actor=actor, storage=storage)
    assert _resolve_source("model provided", context) == "model provided"


def test_resolve_source_requires_source_when_unbound(env) -> None:
    session, storage, actor, _ = env
    context = _Context(session=session, actor=actor, storage=storage)
    with pytest.raises(ValueError):
        _resolve_source(None, context)


def test_quality_input_source_is_optional(env) -> None:
    # 省略 source 现在合法（改由绑定版本提供）
    parsed = QualityInput(response=_empty_response())
    assert parsed.source is None
    parsed_findings = FindingInput(findings=[])
    assert parsed_findings.source is None
