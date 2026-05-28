"""Add INVOICE to the notification_category enum.

Powers the new "Rechnungen" notification category: owners get a
push/email when an Impower invoice is booked for their Liegenschaft.

Postgres 12+ allows ADD VALUE inside a transaction as long as the new
value isn't USED in the same transaction (we only add it here).
Downgrade is a no-op — Postgres can't DROP an enum value, and leaving
it is harmless.

Revision ID: n8k2g6i0d5e1
Revises: m7j1f5h9c4d0
"""

from alembic import op

revision = "n8k2g6i0d5e1"
down_revision = "m7j1f5h9c4d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_category ADD VALUE IF NOT EXISTS 'INVOICE'")


def downgrade() -> None:
    # Postgres has no DROP VALUE; leaving the enum member is harmless.
    pass
