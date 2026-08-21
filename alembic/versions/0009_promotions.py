"""Add governed knowledge promotion.

Revision ID: 0009_promotions
Revises: 0008_reviews
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_promotions"
down_revision: str | None = "0008_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("target_space_id", sa.String(36), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="pending_review"
        ),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("authority_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "public_authority", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_space_id"], ["knowledge_spaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending_review','approved','rejected','indexing','indexed','failed','revoked')",
            name="promotion_status",
        ),
        sa.CheckConstraint(
            "quality_status IN ('passed','failed','needs_human_review')",
            name="promotion_quality_status",
        ),
        sa.CheckConstraint(
            "authority_level >= 0", name="promotion_authority_nonnegative"
        ),
    )
    op.create_index(
        "ix_promotion_requests_version_id", "promotion_requests", ["version_id"]
    )
    op.create_index(
        "ix_promotion_requests_target_space_id",
        "promotion_requests",
        ["target_space_id"],
    )


def downgrade() -> None:
    op.drop_table("promotion_requests")
