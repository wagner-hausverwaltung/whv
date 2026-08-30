"""Fahrtenbuch — DB defaults for created_at/updated_at on trips + trip_invoices.

The two Fahrtenbuch migrations (e5b0y4a8w3x9, g7d2a6c0y5z1) created the
timestamp columns WITHOUT `server_default=now()`, unlike every other table.
TimestampMixin relies on the database default, so every INSERT into trips
failed with a NOT NULL violation on prod/staging (tests build tables from the
models and never saw it). Adds the defaults — no data change.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h8e3b7d1z6a2"
down_revision = "g7d2a6c0y5z1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("trips", "trip_invoices"):
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=sa.text("now()"),
            )


def downgrade() -> None:
    for table in ("trips", "trip_invoices"):
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=None,
            )
