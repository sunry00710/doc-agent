"""Add document review workflow.

Revision ID: 0008_reviews
Revises: 0007_contracts
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_reviews"
down_revision: str | None = "0007_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("reviewer_id", sa.String(36)),
        sa.Column(
            "workflow_revision", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "state IN ('draft','submitted','in_review','changes_requested','resubmitted','approved','promotion_pending','indexed','archived')",
            name="review_state",
        ),
        sa.CheckConstraint(
            "workflow_revision >= 0", name="review_revision_nonnegative"
        ),
    )
    op.create_index(
        "ix_document_reviews_document_id", "document_reviews", ["document_id"]
    )
    op.create_table(
        "review_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("source_range", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_id"], ["document_reviews.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('open','resolved')", name="comment_status"),
    )
    op.create_index("ix_review_comments_review_id", "review_comments", ["review_id"])
    op.create_table(
        "comment_responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("comment_id", sa.String(36), nullable=False),
        sa.Column("response_version_id", sa.String(36), nullable=False),
        sa.Column("assessment", sa.String(32), nullable=False),
        sa.Column(
            "reviewer_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["comment_id"], ["review_comments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["response_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_comment_responses_comment_id", "comment_responses", ["comment_id"]
    )


def downgrade() -> None:
    op.drop_table("comment_responses")
    op.drop_table("review_comments")
    op.drop_table("document_reviews")
