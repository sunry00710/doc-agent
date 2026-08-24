from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.citations import assemble_citation
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeSpace
from app.projects.models import Project
from app.providers.base import CompletionRequest, ModelMessage, ProviderError
from app.providers.fake import FakeProvider


def test_fake_provider_invalid_payload_is_reported():
    provider = FakeProvider([{"unexpected": True}])
    with pytest.raises((AppError, ValueError, AttributeError, ProviderError)):
        provider.complete(
            CompletionRequest(messages=[ModelMessage(role="user", content="hello")])
        )


def test_indexing_hash_corruption_returns_index_failure(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"
            )
        )
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with Session(engine) as session:
        user = User(username="recovery", password_hash="hash")
        session.add(user)
        session.flush()
        project = Project(name="Recovery")
        session.add(project)
        session.flush()
        source = Document(
            project_id=project.id,
            owner_id=user.id,
            title="Recovery",
            domain="test",
            document_type="report",
        )
        session.add(source)
        session.flush()
        space = KnowledgeSpace(kind="shared")
        session.add(space)
        session.flush()
        stored = storage.store("recovery.md", b"original")
        version = DocumentVersion(
            document_id=source.id,
            number=1,
            content_sha256=stored.content_sha256,
            storage_key=stored.storage_key,
            created_by=user.id,
        )
        session.add(version)
        session.flush()
        Path(storage.path_for(stored.storage_key)).write_bytes(b"corrupted")
        with pytest.raises(AppError, match="Knowledge index verification failed"):
            ingest_version(session, storage, UUID(version.id), UUID(space.id))
    engine.dispose()


def test_citation_offset_corruption_is_rejected(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'citation.db'}")
    Base.metadata.create_all(engine)
    storage = FileStorage(
        Settings(environment="test", storage_dir=tmp_path / "storage")
    )
    with Session(engine) as session, pytest.raises(AppError):
        assemble_citation(session, storage, "missing-chunk", "missing-generation")
    engine.dispose()
