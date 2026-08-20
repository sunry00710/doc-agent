"""Add knowledge spaces, generations, chunks, and SQLite FTS5.

Revision ID: 0005_knowledge
Revises: 0004_jobs
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_knowledge"
down_revision: str | None = "0004_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_spaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.String(36)),
        sa.Column("project_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('personal', 'project', 'shared', 'standard')", name="knowledge_space_kind"),
        sa.CheckConstraint("(kind = 'personal' AND owner_id IS NOT NULL AND project_id IS NULL) OR (kind = 'project' AND project_id IS NOT NULL AND owner_id IS NULL) OR (kind IN ('shared', 'standard') AND owner_id IS NULL AND project_id IS NULL)", name="valid_scope"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_spaces_owner_id", "knowledge_spaces", ["owner_id"])
    op.create_index("ix_knowledge_spaces_project_id", "knowledge_spaces", ["project_id"])
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("authority_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("active_generation_id", sa.String(36)),
        sa.CheckConstraint("state IN ('pending_review', 'approved', 'indexed', 'archived')", name="knowledge_document_state"),
        sa.CheckConstraint("authority_level >= 0", name="nonnegative_authority"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("version_id", "space_id", name="version_space"),
    )
    op.create_index("ix_knowledge_documents_version_id", "knowledge_documents", ["version_id"])
    op.create_index("ix_knowledge_documents_space_id", "knowledge_documents", ["space_id"])
    op.create_index("ix_knowledge_documents_active_generation_id", "knowledge_documents", ["active_generation_id"])
    op.create_table(
        "knowledge_generations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("knowledge_document_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.CheckConstraint("state IN ('building', 'active', 'failed')", name="knowledge_generation_state"),
        sa.ForeignKeyConstraint(["knowledge_document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "knowledge_document_id", name="generation_document_pair"),
    )
    op.create_index("ix_knowledge_generations_knowledge_document_id", "knowledge_generations", ["knowledge_document_id"])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("generation_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", "generation_id", name="knowledge_chunk_generation_pk"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="valid_chunk_offsets"),
        sa.ForeignKeyConstraint(["generation_id"], ["knowledge_generations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_chunks_version_id", "knowledge_chunks", ["version_id"])
    op.create_index("ix_knowledge_chunks_generation_version", "knowledge_chunks", ["generation_id", "version_id"])
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)")
        op.execute("""
            CREATE TRIGGER knowledge_documents_active_generation_insert
            BEFORE INSERT ON knowledge_documents
            WHEN NEW.active_generation_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM knowledge_generations
                     WHERE id = NEW.active_generation_id AND knowledge_document_id = NEW.id
                 )
            BEGIN SELECT RAISE(ABORT, 'active generation must belong to knowledge document'); END
        """)
        op.execute("""
            CREATE TRIGGER knowledge_documents_active_generation_update
            BEFORE UPDATE OF active_generation_id, id ON knowledge_documents
            WHEN NEW.active_generation_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM knowledge_generations
                     WHERE id = NEW.active_generation_id AND knowledge_document_id = NEW.id
                 )
            BEGIN SELECT RAISE(ABORT, 'active generation must belong to knowledge document'); END
        """)
    else:
        op.create_foreign_key(
            "active_generation_belongs_to_document",
            "knowledge_documents",
            "knowledge_generations",
            ["active_generation_id", "id"],
            ["id", "knowledge_document_id"],
            deferrable=True,
            initially="DEFERRED",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS knowledge_chunks_fts")
        op.execute("DROP TRIGGER IF EXISTS knowledge_documents_active_generation_update")
        op.execute("DROP TRIGGER IF EXISTS knowledge_documents_active_generation_insert")
    else:
        op.drop_constraint("active_generation_belongs_to_document", "knowledge_documents", type_="foreignkey")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_generations")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_spaces")
