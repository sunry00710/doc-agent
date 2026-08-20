from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).parents[2]


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_0005_upgrade_and_downgrade_schema(tmp_path: Path):
    database = tmp_path / "migration.db"
    config = _config(database)
    command.upgrade(config, "0005_knowledge")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0005_knowledge"
    assert {"knowledge_spaces", "knowledge_documents", "knowledge_generations", "knowledge_chunks"} <= set(inspector.get_table_names())
    assert "knowledge_chunks_fts" in {row[0] for row in engine.connect().execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert any(index["name"] == "ix_knowledge_chunks_generation_version" for index in inspector.get_indexes("knowledge_chunks"))
    assert "knowledge_document_state" in engine.connect().execute(text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_documents' ")).scalar_one()
    assert any(foreign_key["referred_table"] == "document_versions" for foreign_key in inspector.get_foreign_keys("knowledge_documents"))

    command.downgrade(config, "0004_jobs")
    inspector = inspect(engine)
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004_jobs"
    assert not {"knowledge_spaces", "knowledge_documents", "knowledge_generations", "knowledge_chunks"} & set(inspector.get_table_names())
    assert engine.connect().execute(text("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_chunks_fts' ")).scalar_one() == 0
    engine.dispose()


def test_0006_dense_embedding_upgrade_and_downgrade_schema(tmp_path: Path):
    database = tmp_path / "dense-migration.db"
    config = _config(database)
    command.upgrade(config, "0006_dense_embeddings")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0006_dense_embeddings"
    assert "knowledge_embeddings" in inspector.get_table_names()
    assert {column["name"] for column in inspector.get_columns("knowledge_embeddings")} == {
        "chunk_id",
        "generation_id",
        "dimension",
        "vector",
    }
    assert inspector.get_pk_constraint("knowledge_embeddings")["constrained_columns"] == ["chunk_id", "generation_id"]
    assert any(foreign_key["referred_table"] == "knowledge_chunks" for foreign_key in inspector.get_foreign_keys("knowledge_embeddings"))

    command.downgrade(config, "0005_knowledge")
    assert "knowledge_embeddings" not in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_cli_uses_settings_url_unless_config_url_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings_database = tmp_path / "settings.db"
    explicit_database = tmp_path / "explicit.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{settings_database}")

    command.upgrade(Config(str(ROOT / "alembic.ini")), "0001_identity")
    assert settings_database.exists()

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{explicit_database}")
    command.upgrade(config, "0001_identity")
    assert explicit_database.exists()


def test_active_generation_must_belong_to_its_document(tmp_path: Path):
    database = tmp_path / "constraint.db"
    config = _config(database)
    command.upgrade(config, "0005_knowledge")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at) VALUES ('u', 'u', 'x', 'user', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 'p', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO documents (id, project_id, owner_id, title, domain, document_type, status, created_at) VALUES ('d1', 'p', 'u', 'd1', 'x', 'x', 'draft', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO documents (id, project_id, owner_id, title, domain, document_type, status, created_at) VALUES ('d2', 'p', 'u', 'd2', 'x', 'x', 'draft', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO document_versions (id, document_id, number, content_sha256, storage_key, created_by, created_at) VALUES ('v1', 'd1', 1, 'x', 'x', 'u', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO document_versions (id, document_id, number, content_sha256, storage_key, created_by, created_at) VALUES ('v2', 'd2', 1, 'x', 'y', 'u', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO knowledge_spaces (id, kind, owner_id, created_at) VALUES ('s', 'personal', 'u', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO knowledge_documents (id, version_id, space_id, state, authority_level, metadata) VALUES ('kd1', 'v1', 's', 'indexed', 0, '{}')"))
        connection.execute(text("INSERT INTO knowledge_documents (id, version_id, space_id, state, authority_level, metadata) VALUES ('kd2', 'v2', 's', 'indexed', 0, '{}')"))
        connection.execute(text("INSERT INTO knowledge_generations (id, knowledge_document_id, state) VALUES ('g2', 'kd2', 'active')"))
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE knowledge_documents SET active_generation_id = 'g2' WHERE id = 'kd1'"))
    engine.dispose()
