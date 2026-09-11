"""Add dense knowledge embeddings.

Revision ID: 0006_dense_embeddings
Revises: 0005_knowledge
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_dense_embeddings"
down_revision: str | None = "0005_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_embeddings",
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("generation_id", sa.String(36), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id", "generation_id", name="knowledge_embedding_pk"),
        sa.CheckConstraint("dimension > 0", name="positive_embedding_dimension"),
        sa.ForeignKeyConstraint(
            ["chunk_id", "generation_id"],
            ["knowledge_chunks.id", "knowledge_chunks.generation_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_knowledge_embeddings_generation_id", "knowledge_embeddings", ["generation_id"])


def downgrade() -> None:
    op.drop_table("knowledge_embeddings")
