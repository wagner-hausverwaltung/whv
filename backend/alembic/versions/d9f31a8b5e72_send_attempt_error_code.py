"""announcement_send_attempts.error_code

Stable error-code string captured on FAILED rows so the SPA can
render specific copy ("Tageslimit erreicht", "API-Key fehlt", …)
instead of the generic upstream message. The `error_message` column
still carries the raw upstream string for the audit trail.

Default NULL so legacy FAILED rows are untouched.

Revision ID: d9f31a8b5e72
Revises: a72b6e1f9c84
Create Date: 2026-05-25 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9f31a8b5e72"
down_revision: str | Sequence[str] | None = "a72b6e1f9c84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "announcement_send_attempts",
        sa.Column("error_code", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("announcement_send_attempts", "error_code")
