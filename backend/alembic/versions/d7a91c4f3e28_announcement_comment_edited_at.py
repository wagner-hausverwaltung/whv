"""announcement_comments.edited_at

Author-only inline edits on portal comments. NULL = never edited;
non-null timestamp surfaces a "bearbeitet" indicator in the SPA. Edit
history is not preserved on the row — by design, the comment thread
is a low-stakes conversation surface where "I fixed a typo" doesn't
need a versioning audit trail (admin moderation has its own audit
fields).

Revision ID: d7a91c4f3e28
Revises: b3f2a9d47e15
Create Date: 2026-05-25 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a91c4f3e28"
down_revision: str | Sequence[str] | None = "b3f2a9d47e15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "announcement_comments",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("announcement_comments", "edited_at")
