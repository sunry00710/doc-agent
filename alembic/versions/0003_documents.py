"""Create documents and immutable document versions.

Revision ID: 0003_documents
Revises: 0002_projects
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_documents"
down_revision: str | None = "0002_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft')", name=op.f("ck_documents_status")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_documents_owner_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_documents_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_owner_id"), "documents", ["owner_id"])
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("number > 0", name=op.f("ck_document_versions_number_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_document_versions_created_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_document_versions_document_id_documents"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "number", name=op.f("uq_document_versions_document_number")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_document_versions_storage_key")),
    )
    op.create_index(op.f("ix_document_versions_created_by"), "document_versions", ["created_by"])
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER prevent_document_version_update "
            "BEFORE UPDATE ON document_versions "
            "BEGIN SELECT RAISE(ABORT, 'document versions are immutable'); END"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER prevent_document_version_update")
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_created_by"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_documents_project_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_owner_id"), table_name="documents")
    op.drop_table("documents")
