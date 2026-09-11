import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.agent.loop import AgentContext
from app.agent.tools import ToolRegistry
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.knowledge.promotion import PromotionRequest, PromotionStatus
from app.knowledge.promotion_service import (
    activate_promotion,
    request_promotion,
    review_promotion,
    revoke_promotion,
)
from app.knowledge.promotion_tools import register_promotion_tools
from app.knowledge.schemas import SearchQuery
from app.knowledge.search import search
from app.main import create_app
from app.projects.models import MembershipRole, Project, ProjectMember
from app.quality.contracts import (
    ContractRevisionInput,
    Requirement,
    confirm_revision,
    create_contract,
)
from app.quality.models import WritingContract, WritingContractRevision


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


def _promotion_count(session) -> int:
    return session.scalar(
        select(func.count()).select_from(PromotionRequest)
    )


def _tool_context(session, actor, storage) -> AgentContext:
    return AgentContext(
        session=session,
        actor=actor,
        storage=storage,
        actor_id=actor.id,
        confirmed=True,
        idempotency_key=str(uuid4()),
    )


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_promotion_tools(registry)
    return registry


def _client(session, tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite://",
            jwt_secret="test-secret-at-least-thirty-two-bytes",
            storage_dir=tmp_path / "storage",
        )
    )

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": "correct"},
    )
    assert response.status_code == 200
    return {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


def _add_contract(
    session,
    document_id: str,
    author,
    reviewer,
    *,
    requirement: Requirement,
    confirmed: bool,
):
    contract = create_contract(
        session,
        UUID(document_id),
        ContractRevisionInput(
            domain="finance",
            document_type="report",
            subject_organization="Org",
            reporting_period="2026",
            purpose="Test",
            audience="Reviewer",
            requirements=[requirement],
        ),
        author,
    )
    if confirmed:
        confirm_revision(session, contract.id, reviewer)
    return contract


@pytest.mark.parametrize(
    ("global_role", "project_role", "allowed"),
    [
        (Role.admin, MembershipRole.contributor, False),
        (Role.admin, None, False),
        (Role.admin, MembershipRole.owner, True),
        (Role.reviewer, MembershipRole.reviewer, True),
        (Role.user, MembershipRole.owner, False),
    ],
)
def test_governance_capability_matches_promotion_permission(
    tmp_path, global_role, project_role, allowed,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'governance.db'}")
    Base.metadata.create_all(engine)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        author = User(username="author", password_hash=hash_password("correct"))
        actor = User(username="actor", role=global_role, password_hash=hash_password("correct"))
        session.add_all((author, actor))
        session.flush()
        version = _version(session, storage, author)
        document = session.get(Document, version.document_id)
        if project_role is not None:
            session.add(ProjectMember(project_id=document.project_id, user_id=actor.id, membership_role=project_role))
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
        promotion = request_promotion(session, UUID(version.id), UUID(space.id), author, storage)
        session.commit()
        with _client(session, tmp_path) as client:
            headers = _auth_headers(client, actor.username)
            listed = client.get("/api/knowledge/promotions", headers=headers)
            assert listed.status_code == 200
            item = next(item for item in listed.json()["items"] if item["id"] == promotion.id)
            assert item["can_govern"] is allowed
            result = client.post(f"/api/knowledge/promotions/{promotion.id}/review", json={"approved": True}, headers=headers)
            assert result.status_code == (200 if allowed else 403)
    engine.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("findings", [{"category": "forged"}]),
        ("public_authority", True),
        ("authority_level", 999),
    ],
)
def test_promotion_inputs_reject_server_owned_fields(
    tmp_path: Path,
    field: str,
    value: object,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'trust-boundary.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with factory() as session:
        author = User(
            username="boundary-author",
            password_hash=hash_password("correct"),
        )
        session.add(author)
        session.flush()
        version = _version(session, storage, author)
        target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(target)
        session.commit()
        payload = {
            "version_id": version.id,
            "target_space_id": target.id,
            field: value,
        }

        with _client(session, tmp_path) as client:
            response = client.post(
                "/api/knowledge/promotions",
                json=payload,
                headers=_auth_headers(client, author.username),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert _promotion_count(session) == 0

        result, error, _definition, model = (
            _tool_registry().execute_detailed(
                "request_knowledge_promotion",
                json.dumps(payload),
                _tool_context(session, author, storage),
            )
        )
        assert result is None
        assert error == "validation_error"
        assert model is None
        assert _promotion_count(session) == 0
    engine.dispose()


def test_rest_and_agent_compute_the_same_promotion_gate(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'channel-parity.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with factory() as session:
        author = User(
            username="parity-author",
            password_hash=hash_password("correct"),
        )
        reviewer = User(
            username="parity-reviewer",
            password_hash=hash_password("correct"),
            role=Role.reviewer,
        )
        session.add_all((author, reviewer))
        session.flush()
        rest_version = _version(session, storage, author)
        tool_version = _version(session, storage, author)
        for version in (rest_version, tool_version):
            document = session.get(Document, version.document_id)
            session.add(
                ProjectMember(
                    project_id=document.project_id,
                    user_id=reviewer.id,
                    membership_role=MembershipRole.reviewer,
                )
            )
            _add_contract(
                session,
                document.id,
                author,
                reviewer,
                requirement=Requirement(
                    id="optional",
                    text="missing optional disclosure",
                    mandatory=False,
                ),
                confirmed=False,
            )
        rest_target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        tool_target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add_all((rest_target, tool_target))
        session.commit()

        with _client(session, tmp_path) as client:
            response = client.post(
                "/api/knowledge/promotions",
                json={
                    "version_id": rest_version.id,
                    "target_space_id": rest_target.id,
                },
                headers=_auth_headers(client, author.username),
            )
        assert response.status_code == 201

        result, error, _definition, _model = (
            _tool_registry().execute_detailed(
                "request_knowledge_promotion",
                json.dumps(
                    {
                        "version_id": tool_version.id,
                        "target_space_id": tool_target.id,
                    }
                ),
                _tool_context(session, author, storage),
            )
        )
        assert error is None
        rest_request = session.get(PromotionRequest, response.json()["id"])
        tool_request = session.get(PromotionRequest, str(result["request_id"]))
        for request in (rest_request, tool_request):
            assert request.status == PromotionStatus.pending_review
            assert request.quality_status == "needs_human_review"
            assert request.policy_version == "promotion-contract-gate-v2"
            assert request.authority_level == 0
            assert request.public_authority is False
            assert {
                item["category"] for item in request.findings
            } == {
                "contract_requirement",
                "contract_unconfirmed",
            }
        assert {
            item["category"]
            for item in rest_request.findings
        } == {
            item["category"]
            for item in tool_request.findings
        }
    engine.dispose()


def test_mandatory_gate_returns_validation_error_to_both_channels(
    tmp_path: Path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'mandatory-parity.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with factory() as session:
        author = User(
            username="mandatory-author",
            password_hash=hash_password("correct"),
        )
        reviewer = User(
            username="mandatory-reviewer",
            password_hash=hash_password("correct"),
            role=Role.reviewer,
        )
        session.add_all((author, reviewer))
        session.flush()
        rest_version = _version(session, storage, author)
        tool_version = _version(session, storage, author)
        for version in (rest_version, tool_version):
            document = session.get(Document, version.document_id)
            session.add(
                ProjectMember(
                    project_id=document.project_id,
                    user_id=reviewer.id,
                    membership_role=MembershipRole.reviewer,
                )
            )
            _add_contract(
                session,
                document.id,
                author,
                reviewer,
                requirement=Requirement(
                    id="mandatory",
                    text="missing mandatory disclosure",
                    mandatory=True,
                ),
                confirmed=True,
            )
        rest_target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        tool_target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add_all((rest_target, tool_target))
        session.commit()

        with _client(session, tmp_path) as client:
            response = client.post(
                "/api/knowledge/promotions",
                json={
                    "version_id": rest_version.id,
                    "target_space_id": rest_target.id,
                },
                headers=_auth_headers(client, author.username),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

        result, error = _tool_registry().execute(
            "request_knowledge_promotion",
            json.dumps(
                {
                    "version_id": tool_version.id,
                    "target_space_id": tool_target.id,
                }
            ),
            _tool_context(session, author, storage),
        )
        assert result is None
        assert error == "validation_error"
        assert _promotion_count(session) == 0
    engine.dispose()


def test_promotion_requires_gate_reviewer_and_revocation_hides_result(
    tmp_path: Path,
):
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

        request = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            storage,
        )
        assert request.public_authority is False
        assert request.authority_level == 0
        assert request.findings == []
        duplicate = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            storage,
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

        resubmitted = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            storage,
        )
        assert resubmitted.id != request.id
        assert resubmitted.status == PromotionStatus.pending_review

        revoke_promotion(session, UUID(resubmitted.id), reviewer)
        session.commit()
        resubmitted_again = request_promotion(
            session,
            UUID(version.id),
            UUID(target.id),
            author,
            storage,
        )
        assert resubmitted_again.id not in {request.id, resubmitted.id}
        assert resubmitted_again.status == PromotionStatus.pending_review
    engine.dispose()


def test_contract_quality_gate_controls_promotion(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'contract-promotion.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        author = User(username="contract-author", password_hash=hash_password("correct"))
        reviewer = User(username="contract-reviewer", password_hash=hash_password("correct"), role=Role.reviewer)
        session.add_all((author, reviewer))
        session.flush()
        version = _version(session, storage, author)
        document = session.get(Document, version.document_id)
        session.add(ProjectMember(project_id=document.project_id, user_id=reviewer.id, membership_role=MembershipRole.reviewer))
        target = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(target)
        session.flush()

        contract = create_contract(
            session,
            UUID(document.id),
            ContractRevisionInput(
                domain="finance",
                document_type="report",
                subject_organization="Org",
                reporting_period="2026",
                purpose="Test",
                audience="Reviewer",
                requirements=[Requirement(id="optional", text="非强制披露", mandatory=False)],
            ),
            author,
        )
        pending = request_promotion(session, UUID(version.id), UUID(target.id), author, storage)
        assert pending.quality_status == "needs_human_review"
        assert any(item["category"] == "contract_unconfirmed" for item in pending.findings)
        revoke_promotion(session, UUID(pending.id), reviewer)

        contract_model = session.get(WritingContract, str(contract.id))
        confirm_revision(session, UUID(contract_model.id), reviewer)
        optional = request_promotion(session, UUID(version.id), UUID(target.id), author, storage)
        assert optional.quality_status == "needs_human_review"
        assert optional.findings[0]["requirement_id"] == "optional"
        revoke_promotion(session, UUID(optional.id), reviewer)

        contract_model.active_revision += 1
        session.add(WritingContractRevision(
            contract_id=contract_model.id,
            revision=contract_model.active_revision,
            domain="finance",
            document_type="report",
            subject_organization="Org",
            reporting_period="2026",
            purpose="Test",
            audience="Reviewer",
            requirements=[{"id": "mandatory", "text": "必须披露金额", "mandatory": True}],
            standard_ids=[],
            precedent_ids=[],
            reviewer_id=reviewer.id,
            reviewer_confirmed=True,
            created_by=author.id,
        ))
        session.flush()
        with pytest.raises(AppError, match="blocked by quality gate"):
            request_promotion(session, UUID(version.id), UUID(target.id), author, storage)

    engine.dispose()
