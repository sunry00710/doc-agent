from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import (
    KnowledgeDocument,
    KnowledgeSpace,
    KnowledgeSpaceKind,
    KnowledgeState,
)
from app.knowledge.schemas import SearchQuery
from app.knowledge.search import search
from app.projects.models import MembershipRole, Project, ProjectMember


def _setup(session: Session, storage: FileStorage, owner: User, content: str) -> DocumentVersion:
    project = Project(name="Knowledge project")
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner))
    stored = storage.store("source.md", content.encode())
    document = Document(project_id=project.id, owner_id=owner.id, title="Audit", domain="finance", document_type="report")
    session.add(document)
    session.flush()
    version = DocumentVersion(document_id=document.id, number=1, content_sha256=stored.content_sha256, storage_key=stored.storage_key, created_by=owner.id)
    session.add(version)
    session.flush()
    return version


def test_search_authorizes_spaces_before_ranking(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        outsider = User(username="outsider", password_hash=hash_password("correct"), role=Role.reviewer)
        session.add_all((owner, outsider))
        session.flush()
        version = _setup(session, storage, owner, "# 私人\n\n仅所有者可见的审计密语。")
        personal = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add(personal)
        session.flush()
        ingest_version(session, storage, UUID(version.id), UUID(personal.id))
        session.commit()

        assert search(session, storage, SearchQuery(query="审计密语"), owner)
        assert search(session, storage, SearchQuery(query="审计密语"), outsider) == []
    engine.dispose()


def test_space_and_state_isolation_matrix(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'isolation-matrix.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        member = User(username="member", password_hash=hash_password("correct"))
        outsider = User(username="outsider", password_hash=hash_password("correct"))
        reviewer = User(username="reviewer", password_hash=hash_password("correct"), role=Role.reviewer)
        session.add_all((owner, member, outsider, reviewer))
        session.flush()
        project = Project(name="Shared project")
        session.add(project)
        session.flush()
        session.add_all((
            ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner),
            ProjectMember(project_id=project.id, user_id=member.id, membership_role=MembershipRole.contributor),
        ))

        cases = [
            (KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id), owner, "personal-owner"),
            (KnowledgeSpace(kind=KnowledgeSpaceKind.project, project_id=project.id), member, "project-member"),
            (KnowledgeSpace(kind=KnowledgeSpaceKind.shared), outsider, "shared-indexed"),
            (KnowledgeSpace(kind=KnowledgeSpaceKind.standard), reviewer, "standard-indexed"),
        ]
        hidden_states = (KnowledgeState.pending_review, KnowledgeState.approved, KnowledgeState.archived)
        for number, (space, visible_actor, token) in enumerate(cases, start=1):
            stored = storage.store(f"{token}.md", token.encode())
            source = Document(project_id=project.id, owner_id=owner.id, title=token, domain="finance", document_type="report")
            session.add_all((space, source))
            session.flush()
            version = DocumentVersion(document_id=source.id, number=number, content_sha256=stored.content_sha256, storage_key=stored.storage_key, created_by=owner.id)
            session.add(version)
            session.flush()
            indexed = ingest_version(session, storage, UUID(version.id), UUID(space.id))
            for state in hidden_states:
                hidden = KnowledgeDocument(version_id=version.id, space_id=space.id, state=state)
                # Each hidden document uses a different source/version to preserve version-space uniqueness.
                hidden_source = Document(project_id=project.id, owner_id=owner.id, title=f"{token}-{state.value}", domain="finance", document_type="report")
                hidden_stored = storage.store(f"{token}-{state.value}.md", f"{token}-{state.value}".encode())
                session.add(hidden_source)
                session.flush()
                hidden_version = DocumentVersion(document_id=hidden_source.id, number=1, content_sha256=hidden_stored.content_sha256, storage_key=hidden_stored.storage_key, created_by=owner.id)
                session.add(hidden_version)
                session.flush()
                hidden.version_id = hidden_version.id
                session.add(hidden)
                ingest_version(session, storage, UUID(hidden_version.id), UUID(space.id))
                hidden.state = state
            assert indexed.state == KnowledgeState.indexed
        session.commit()

        assert search(session, storage, SearchQuery(query="project-member"), member)
        assert search(session, storage, SearchQuery(query="project-member"), outsider) == []
        assert search(session, storage, SearchQuery(query="project-member"), reviewer) == []
        assert search(session, storage, SearchQuery(query="personal-owner"), owner)
        assert search(session, storage, SearchQuery(query="personal-owner"), member) == []
        assert search(session, storage, SearchQuery(query="personal-owner"), reviewer) == []
        for actor in (owner, member, outsider, reviewer):
            assert search(session, storage, SearchQuery(query="shared-indexed"), actor)
            assert search(session, storage, SearchQuery(query="standard-indexed"), actor)
            for state in hidden_states:
                assert search(session, storage, SearchQuery(query=f"shared-indexed-{state.value}"), actor) == []
    engine.dispose()


def test_fts_filters_unauthorized_chunk_generation_pairs(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'generation-pairs.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        outsider = User(username="outsider", password_hash=hash_password("correct"))
        session.add_all((owner, outsider))
        session.flush()
        allowed_version = _setup(session, storage, outsider, "# Shared\n\nneedle")
        private_version = _setup(session, storage, owner, "# Private\n\nneedle needle needle needle")
        shared = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        personal = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add_all((shared, personal))
        session.flush()
        ingest_version(session, storage, UUID(allowed_version.id), UUID(shared.id))
        ingest_version(session, storage, UUID(private_version.id), UUID(personal.id))
        session.commit()

        allowed_chunk_id = session.execute(text("SELECT chunk_id FROM knowledge_chunks_fts WHERE text = 'needle'")) .scalar_one()
        private_generation_id = session.execute(text("SELECT active_generation_id FROM knowledge_documents WHERE version_id = :version_id"), {"version_id": private_version.id}).scalar_one()
        session.execute(text("UPDATE knowledge_chunks_fts SET chunk_id = :chunk_id WHERE generation_id = :generation_id"), {"chunk_id": allowed_chunk_id, "generation_id": private_generation_id})
        session.commit()

        hits = search(session, storage, SearchQuery(query="needle", limit=1), outsider)
        assert len(hits) == 1
        assert hits[0].version_id == UUID(allowed_version.id)
    engine.dispose()


def test_fts_filters_unauthorized_chunks_before_ranking_and_limit(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ranking.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        outsider = User(username="outsider", password_hash=hash_password("correct"))
        session.add_all((owner, outsider))
        session.flush()
        allowed_version = _setup(session, storage, outsider, "# 共享\n\nneedle")
        private_version = _setup(session, storage, owner, "# 私密\n\nneedle needle needle needle")
        shared = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        personal = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add_all((shared, personal))
        session.flush()
        ingest_version(session, storage, UUID(allowed_version.id), UUID(shared.id))
        ingest_version(session, storage, UUID(private_version.id), UUID(personal.id))
        session.commit()
        assert session.execute(text("SELECT count(*) FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH 'needle'")).scalar_one() == 2

        hits = search(session, storage, SearchQuery(query="needle", limit=1), outsider)
        assert len(hits) == 1
        assert hits[0].version_id == UUID(allowed_version.id)
    engine.dispose()
