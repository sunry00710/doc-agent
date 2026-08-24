from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSpace,
    KnowledgeSpaceKind,
)
from app.knowledge.schemas import SearchQuery
from app.knowledge.search import _DENSE_CANDIDATE_LIMIT, DenseBackend, search
from app.projects.models import MembershipRole, Project, ProjectMember


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.asarray([self.vectors[text] for text in texts], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.asarray(self.vectors[text], dtype=np.float32)


class BrokenEmbeddingProvider(EmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.ones((max(0, len(texts) - 1), 3), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.ones(3, dtype=np.float32)


class UnavailableEmbeddingProvider(EmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("model unavailable")

    def embed_query(self, text: str) -> np.ndarray:
        raise RuntimeError("model unavailable")


def setup_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dense.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    return engine, sessionmaker(bind=engine, expire_on_commit=False), FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))


def add_version(session: Session, storage: FileStorage, owner: User, title: str, content: str, number: int = 1) -> DocumentVersion:
    project = Project(name=f"{title} project")
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner))
    document = Document(project_id=project.id, owner_id=owner.id, title=title, domain="finance", document_type="report")
    stored = storage.store(f"{title}.md", content.encode())
    session.add(document)
    session.flush()
    version = DocumentVersion(document_id=document.id, number=number, content_sha256=stored.content_sha256, storage_key=stored.storage_key, created_by=owner.id)
    session.add(version)
    session.flush()
    return version


def test_dense_and_hybrid_search_use_fake_embeddings(tmp_path: Path):
    engine, factory, storage = setup_database(tmp_path)
    vectors = {"alpha": [1, 0, 0], "beta": [0, 1, 0], "semantic query": [0.9, 0.1, 0]}
    provider = FakeEmbeddingProvider(vectors)
    with factory() as session:
        actor = User(username="actor", password_hash=hash_password("correct"))
        session.add(actor)
        session.flush()
        version = add_version(session, storage, actor, "Dense", "alpha\n\nbeta")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
        ingest_version(session, storage, UUID(version.id), UUID(space.id), embedding_provider=provider)
        session.commit()

        dense = search(session, storage, SearchQuery(query="semantic query", mode="dense"), actor, embedding_provider=provider)
        hybrid = search(session, storage, SearchQuery(query="alpha", mode="hybrid"), actor, embedding_provider=provider)

        assert [hit.quote for hit in dense] == ["alpha", "beta"]
        assert hybrid[0].quote == "alpha"
    engine.dispose()


def test_dense_filters_unauthorized_generations_before_vector_scoring(tmp_path: Path):
    engine, factory, storage = setup_database(tmp_path)
    provider = FakeEmbeddingProvider({"allowed": [0, 1, 0], "private": [1, 0, 0], "query": [1, 0, 0]})
    with factory() as session:
        owner = User(username="owner", password_hash=hash_password("correct"))
        outsider = User(username="outsider", password_hash=hash_password("correct"))
        session.add_all((owner, outsider))
        session.flush()
        allowed_version = add_version(session, storage, outsider, "Allowed", "allowed")
        private_version = add_version(session, storage, owner, "Private", "private")
        shared = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        personal = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
        session.add_all((shared, personal))
        session.flush()
        ingest_version(session, storage, UUID(allowed_version.id), UUID(shared.id), embedding_provider=provider)
        private_document = ingest_version(session, storage, UUID(private_version.id), UUID(personal.id), embedding_provider=provider)
        session.flush()
        private_embedding = session.scalar(select(KnowledgeEmbedding).where(KnowledgeEmbedding.generation_id == private_document.active_generation_id))
        assert private_embedding is not None
        private_embedding.vector = b"corrupt"
        session.commit()

        hits = search(session, storage, SearchQuery(query="query", mode="dense", limit=1), outsider, embedding_provider=provider)

        assert len(hits) == 1
        assert hits[0].version_id == UUID(allowed_version.id)
    engine.dispose()


def test_failed_dense_rebuild_preserves_previous_active_generation(tmp_path: Path):
    engine, factory, storage = setup_database(tmp_path)
    provider = FakeEmbeddingProvider({"alpha": [1, 0, 0], "query": [1, 0, 0]})
    with factory() as session:
        actor = User(username="actor", password_hash=hash_password("correct"))
        session.add(actor)
        session.flush()
        version = add_version(session, storage, actor, "Atomic", "alpha")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
        document = ingest_version(session, storage, UUID(version.id), UUID(space.id), embedding_provider=provider)
        session.commit()
        previous_generation_id = document.active_generation_id

        with pytest.raises(AppError) as error:
            ingest_version(session, storage, UUID(version.id), UUID(space.id), rebuild=True, embedding_provider=BrokenEmbeddingProvider())
        session.rollback()

        document = session.get(KnowledgeDocument, document.id)
        assert document is not None
        assert document.active_generation_id == previous_generation_id
        assert session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.generation_id != previous_generation_id)).all() == []
        assert search(session, storage, SearchQuery(query="query", mode="dense"), actor, embedding_provider=provider)
        assert error.value.code == "index_failure"
    engine.dispose()


def test_reingestion_upgrades_keyword_only_active_generation(tmp_path: Path):
    engine, factory, storage = setup_database(tmp_path)
    provider = FakeEmbeddingProvider({"alpha": [1, 0, 0], "query": [1, 0, 0]})
    with factory() as session:
        actor = User(username="actor", password_hash=hash_password("correct"))
        session.add(actor)
        session.flush()
        version = add_version(session, storage, actor, "Upgrade", "alpha")
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
        document = ingest_version(session, storage, UUID(version.id), UUID(space.id))
        session.commit()
        keyword_generation_id = document.active_generation_id

        upgraded = ingest_version(session, storage, UUID(version.id), UUID(space.id), embedding_provider=provider)
        session.commit()

        assert upgraded.active_generation_id != keyword_generation_id
        assert session.scalar(select(KnowledgeEmbedding).where(KnowledgeEmbedding.generation_id == upgraded.active_generation_id)) is not None
        assert search(session, storage, SearchQuery(query="query", mode="dense"), actor, embedding_provider=provider)
    engine.dispose()


def test_dense_retrieval_has_a_bounded_authorized_candidate_set(tmp_path: Path):
    engine, factory, _storage = setup_database(tmp_path)
    provider = FakeEmbeddingProvider({"query": [1, 0, 0]})
    with factory() as session:
        actor = User(username="actor", password_hash=hash_password("correct"))
        session.add(actor)
        session.commit()
        generation_id = "generation"
        session.add_all(
            KnowledgeEmbedding(
                chunk_id=f"chunk-{index}",
                generation_id=generation_id,
                dimension=3,
                vector=np.asarray([1, 0, 0], dtype=np.float32).tobytes(),
            )
            for index in range(_DENSE_CANDIDATE_LIMIT + 1)
        )
        session.commit()

        ranked = DenseBackend(session, provider).search("query", frozenset({generation_id}), _DENSE_CANDIDATE_LIMIT + 1)

        assert len(ranked) == _DENSE_CANDIDATE_LIMIT
    engine.dispose()


def test_dense_provider_failure_uses_index_error_contract(tmp_path: Path):
    engine, factory, _storage = setup_database(tmp_path)
    with factory() as session:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO knowledge_embeddings (chunk_id, generation_id, dimension, vector) VALUES ('chunk', 'generation', 3, :vector)"),
                {"vector": np.asarray([1, 0, 0], dtype=np.float32).tobytes()},
            )

        with pytest.raises(AppError) as error:
            DenseBackend(session, UnavailableEmbeddingProvider()).search("query", frozenset({"generation"}), 1)

        assert error.value.code == "index_failure"
    engine.dispose()


def test_dense_database_failure_uses_index_error_contract(tmp_path: Path):
    engine, factory, _storage = setup_database(tmp_path)
    provider = FakeEmbeddingProvider({"query": [1, 0, 0]})
    with factory() as session:
        actor = User(username="actor", password_hash=hash_password("correct"))
        session.add(actor)
        session.commit()
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE knowledge_embeddings"))

        with pytest.raises(AppError) as error:
            DenseBackend(session, provider).search("query", frozenset({"generation"}), 1)

        assert error.value.code == "index_failure"
    engine.dispose()


def test_search_mode_is_strictly_validated():
    with pytest.raises(ValueError):
        SearchQuery(query="query", mode="semantic")
