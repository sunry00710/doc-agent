from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.knowledge.promotion import PromotionStatus
from app.knowledge.promotion_service import (
    activate_promotion,
    request_promotion,
    review_promotion,
    revoke_promotion,
)
from app.knowledge.schemas import SearchQuery
from app.knowledge.search import search
from app.projects.models import MembershipRole, Project, ProjectMember
from app.quality.gates import evaluate_quality_gate


def _version(session, storage, owner):
    project = Project(name="Promotion project")
    session.add(project)
    session.flush()
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            membership_role=MembershipRole.owner,
        )
    )
    stored = storage.store("public.md", b"# Approved\n\nretrievable promotion evidence")
    document = Document(
        project_id=project.id,
        owner_id=owner.id,
        title="Approved",
        domain="finance",
        document_type="report",
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        number=1,
        content_sha256=stored.content_sha256,
        storage_key=stored.storage_key,
        created_by=owner.id,
    )
    session.add(version)
    session.flush()
    return version


def test_promotion_requires_gate_reviewer_and_revocation_hides_result(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'promotion.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with factory() as session:
        author = User(username="author", password_hash=hash_password("correct"))
        reviewer = User(
            username="reviewer",
            password_hash=hash_password("correct"),
            role=Role.reviewer,
        )
        session.add_all((author, reviewer))
        session.flush()
        version = _version(session, storage, author)
        project_id = session.get(Document, version.document_id).project_id
        session.add(
            ProjectMember(
                project_id=project_id,
                user_id=reviewer.id,
                membership_role=MembershipRole.reviewer,
            )
        )
        target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(target)
        session.flush()

        with pytest.raises(AppError, match="Invalid quality gate result"):
            request_promotion(
                session,
                UUID(version.id),
                UUID(target.id),
                author,
                evaluate_quality_gate([{"severity": "high", "mandatory": True}]),
            )

        request = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            evaluate_quality_gate([]),
        )
        duplicate = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            evaluate_quality_gate([]),
        )
        assert duplicate.id == request.id
        assert request.status == PromotionStatus.pending_review
        with pytest.raises(AppError, match="Reviewer approval required"):
            review_promotion(session, UUID(request.id), author, True)
        approved = review_promotion(session, UUID(request.id), reviewer, True)
        assert approved.status == PromotionStatus.approved
        activated = activate_promotion(session, UUID(request.id), storage, reviewer)
        session.commit()
        assert activated.status == PromotionStatus.indexed
        assert search(session, storage, SearchQuery(query="promotion evidence"), author)

        revoked = revoke_promotion(session, UUID(request.id), reviewer)
        session.commit()
        assert revoked.status == PromotionStatus.revoked
        assert (
            search(session, storage, SearchQuery(query="promotion evidence"), author)
            == []
        )
    engine.dispose()
