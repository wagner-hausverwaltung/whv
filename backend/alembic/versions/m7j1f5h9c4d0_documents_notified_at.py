"""Add `documents.notified_at` for the new-document notification.

Stamped when owners have been emailed/pushed that a relevant new
document is available, so the post-sync pass never re-notifies. The
upgrade baselines every EXISTING row to now() so the first post-deploy
sync only fires for genuinely new documents — never the whole backlog.

Revision ID: m7j1f5h9c4d0
Revises: l6i0e4g8b3c9
"""

import sqlalchemy as sa
from alembic import op

revision = "m7j1f5h9c4d0"
down_revision = "l6i0e4g8b3c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Baseline: everything that already exists counts as "already
    # notified" so the first sync after deploy doesn't blast owners
    # about the entire document archive.
    op.execute("UPDATE documents SET notified_at = now()")


def downgrade() -> None:
    op.drop_column("documents", "notified_at")
