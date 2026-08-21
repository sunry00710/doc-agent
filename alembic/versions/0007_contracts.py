"""Add versioned writing contracts.

Revision ID: 0007_contracts
Revises: 0006_dense_embeddings
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_contracts"
down_revision: str | None = "0006_dense_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "writing_contracts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("active_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_id", name="writing_contract_document"),
        sa.CheckConstraint("active_revision > 0", name="positive_contract_revision"),
    )
    op.create_index("ix_writing_contracts_project_id", "writing_contracts", ["project_id"])
    op.create_table(
        "writing_contract_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(255), nullable=False),
        sa.Column("subject_organization", sa.String(255), nullable=False),
        sa.Column("reporting_period", sa.String(255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("standard_ids", sa.JSON(), nullable=False),
        sa.Column("precedent_ids", sa.JSON(), nullable=False),
        sa.Column("reviewer_id", sa.String(36)),
        sa.Column("reviewer_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["writing_contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("contract_id", "revision", name="contract_revision_number"),
        sa.CheckConstraint("revision > 0", name="positive_contract_revision_number"),
    )
    op.create_index("ix_contract_revisions_contract_id", "writing_contract_revisions", ["contract_id"])


def downgrade() -> None:
    op.drop_table("writing_contract_revisions")
    op.drop_table("writing_contracts")
