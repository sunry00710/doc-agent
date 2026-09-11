from pathlib import Path
from threading import Barrier, Thread
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.citations import assemble_citation
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import (
    GenerationState,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeSpace,
    KnowledgeSpaceKind,
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


def test_search_citation_reloads_and_verifies_immutable_content(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'citation.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        project = Project(name="Citation")
        session.add_all((owner, project))
        session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner))
        stored = storage.store("citation.md", "# 结论\n\n审计结论可核验。".encode())
        document = Document(project_id=project.id, owner_id=owner.id, title="审计报告", domain="finance", document_type="report")
        session.add(document)
        session.flush()
        version = DocumentVersion(document_id=document.id, number=1, content_sha256=stored.content_sha256, storage_key=stored.storage_key, created_by=owner.id)
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add_all((version, space))
        session.flush()
        ingest_version(session, storage, UUID(version.id), UUID(space.id))
        session.commit()

        hit = search(session, storage, SearchQuery(query="可核验"), owner)[0]
        citation = assemble_citation(session, storage, hit.chunk_id)
        assert citation.quote == "审计结论可核验。"
        assert citation.title == "审计报告"

        storage.path_for(version.storage_key).write_bytes(b"tampered")
        with pytest.raises(AppError, match="Knowledge index verification failed") as caught:
            assemble_citation(session, storage, hit.chunk_id)
        assert caught.value.code == "index_failure"
    engine.dispose()


def test_existing_document_without_active_generation_is_rebuilt(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'inactive-document.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="inactive-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.flush()
        version = _setup(session, storage, owner, "# 结论\n\n可完成索引。")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add(space)
        session.flush()
        incomplete = KnowledgeDocument(version_id=version.id, space_id=space.id)
        session.add(incomplete)
        session.flush()
        session.add(KnowledgeGeneration(knowledge_document_id=incomplete.id, state=GenerationState.building))
        session.commit()

        indexed = ingest_version(session, storage, UUID(version.id), UUID(space.id))
        session.commit()
        assert indexed.active_generation_id is not None
        assert session.get(KnowledgeGeneration, indexed.active_generation_id).state == GenerationState.active
    engine.dispose()


def test_punctuation_only_query_is_a_validation_error(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'punctuation.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        actor = User(username="punctuation", password_hash=hash_password("correct"))
        session.add(actor)
        session.flush()
        with pytest.raises(AppError, match="Invalid knowledge search query") as caught:
            search(session, storage, SearchQuery(query="!?，。"), actor)
        assert caught.value.code == "validation_error"
    engine.dispose()


def test_concurrent_ingestion_converges_on_one_complete_active_generation(tmp_path: Path):
    database = tmp_path / "concurrent-ingestion.db"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0005_knowledge")

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 0})
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode = WAL"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="concurrent-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.flush()
        version = _setup(session, storage, owner, "# 结论\n\n并发索引必须完整。\n\n## 依据\n\n所有分块必须进入 FTS。")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add(space)
        session.commit()
        version_id, space_id = UUID(version.id), UUID(space.id)

    start = Barrier(3)
    returned_generation_ids: list[str | None] = []
    failures: list[Exception] = []

    def ingest() -> None:
        try:
            with factory() as session:
                start.wait()
                document = ingest_version(session, storage, version_id, space_id)
                assert document.active_generation_id is not None
                returned_generation_ids.append(document.active_generation_id)
                session.commit()
        except Exception as exc:  # noqa: BLE001 - worker failures must be reported to the test thread.
            failures.append(exc)

    workers = [Thread(target=ingest) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join()

    assert not failures
    assert len(returned_generation_ids) == 2
    with factory() as session:
        documents = session.execute(text("SELECT id, active_generation_id FROM knowledge_documents WHERE version_id = :version_id AND space_id = :space_id"), {"version_id": str(version_id), "space_id": str(space_id)}).all()
        assert len(documents) == 1
        document_id, active_generation_id = documents[0]
        assert active_generation_id is not None
        assert set(returned_generation_ids) == {active_generation_id}
        assert session.execute(text("SELECT count(*) FROM knowledge_generations WHERE knowledge_document_id = :document_id AND state = 'active'"), {"document_id": document_id}).scalar_one() == 1
        chunk_count = session.execute(text("SELECT count(*) FROM knowledge_chunks WHERE generation_id = :generation_id"), {"generation_id": active_generation_id}).scalar_one()
        assert chunk_count > 0
        assert session.execute(text("SELECT count(*) FROM knowledge_chunks_fts WHERE generation_id = :generation_id"), {"generation_id": active_generation_id}).scalar_one() == chunk_count
    engine.dispose()


def test_failed_reindex_preserves_active_generation_and_fts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'atomic.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.flush()
        version = _setup(session, storage, owner, "# 结论\n\n原始可检索结论。\n\n## 补充\n\n第二段用于注入失败。")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add(space)
        session.flush()
        document = ingest_version(session, storage, UUID(version.id), UUID(space.id))
        session.commit()
        first_generation = document.active_generation_id

        original_execute = session.execute
        fts_inserts = 0

        def fail_after_fts_insert(statement, *args, **kwargs):
            nonlocal fts_inserts
            if "INSERT INTO knowledge_chunks_fts" in str(statement):
                fts_inserts += 1
                if fts_inserts == 2:
                    raise RuntimeError("injected FTS failure")
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", fail_after_fts_insert)
        with pytest.raises(AppError, match="Knowledge index verification failed") as caught:
            ingest_version(session, storage, UUID(version.id), UUID(space.id), rebuild=True)
        assert caught.value.code == "index_failure"
        session.rollback()
        session.expire_all()

        assert session.get(type(document), document.id).active_generation_id == first_generation
        assert session.execute(text("SELECT count(*) FROM knowledge_generations WHERE state = 'failed'")).scalar_one() == 0
        assert session.execute(text("SELECT count(*) FROM knowledge_chunks_fts WHERE generation_id != :generation_id"), {"generation_id": first_generation}).scalar_one() == 0
        assert session.execute(text("SELECT count(*) FROM knowledge_chunks_fts WHERE generation_id = :generation_id"), {"generation_id": first_generation}).scalar_one() > 0
    engine.dispose()


def test_hybrid_search_falls_back_to_keyword_without_embeddings(tmp_path: Path):
    """EMBEDDING_ENABLED=false（内网离线部署）时，hybrid 必须降级为关键词，而不是 500。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'keyword-fallback.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = User(username="offline-owner", password_hash=hash_password("correct"))
        session.add(owner)
        session.flush()
        version = _setup(session, storage, owner, "# 结论\n\n供应商报价三家比对材料已归档。")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add(space)
        session.flush()
        ingest_version(session, storage, UUID(version.id), UUID(space.id))
        session.commit()

        hits = search(
            session,
            storage,
            SearchQuery(query="供应商报价", mode="hybrid"),
            owner,
            embedding_provider=None,
        )
        assert [hit.quote for hit in hits] == ["供应商报价三家比对材料已归档。"]

        with pytest.raises(AppError) as caught:
            search(
                session,
                storage,
                SearchQuery(query="供应商报价", mode="dense"),
                owner,
                embedding_provider=None,
            )
        assert caught.value.code == "index_failure"
    engine.dispose()
