"""announcements.excluded_user_ids + extra_emails

Per-Mitteilung recipient override columns. The auto-resolved recipient
set (audience role + per-unit filter via the contact → contract chain)
is the baseline; the admin can subtract specific users (`excluded_user_ids`)
and add free-text email addresses for non-portal recipients
(`extra_emails`). Final send set = (auto − excluded) ∪ extras,
re-resolved on every send so new portal users joining the property
automatically get future fan-outs.

Postgres array columns are first-class — queries stay simple and the
schema doesn't grow another junction table. Both default to '{}' so
existing rows behave identically to today.

Revision ID: c5e9d8a4f612
Revises: f2c8a9bd05e7
Create Date: 2026-05-25 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e9d8a4f612"
down_revision: str | Sequence[str] | None = "f2c8a9bd05e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "announcements",
        sa.Column(
            "excluded_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "announcements",
        sa.Column(
            "extra_emails",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("announcements", "extra_emails")
    op.drop_column("announcements", "excluded_user_ids")
