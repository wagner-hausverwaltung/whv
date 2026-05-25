"""announcement_comment_versions

Per-edit version snapshot for portal comment authors. Every time an
author hits Save on their own comment, the *prior* body is captured
here before the row is mutated. Reading the chain back gives the
audit trail "this is what was originally written, here's what the
author replaced it with at 14:32".

`recorded_at` is when the version was archived (= the timestamp of
the edit that replaced it), not when the original body was first
typed. The `announcement_comments.created_at` of the parent row
gives the original-write time.

`author_user_id` is the author of the edit, not the (always
identical) author of the comment — captured so an admin moderating
the table can confirm authorship without joining back to the parent.

Revision ID: a72b6e1f9c84
Revises: c5e9d8a4f612
Create Date: 2026-05-25 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a72b6e1f9c84"
down_revision: str | Sequence[str] | None = "c5e9d8a4f612"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "announcement_comment_versions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "comment_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "author_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["announcement_comments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcement_comment_versions_thread",
        "announcement_comment_versions",
        ["comment_id", "recorded_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_announcement_comment_versions_thread",
        table_name="announcement_comment_versions",
    )
    op.drop_table("announcement_comment_versions")
