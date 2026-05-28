"""Add PLAN_ADJUSTMENT to the notification_category enum.

Powers the "Hausgeld-Anpassung" category: owners get notified when the
Verwalter marks a plan-adjustment suggestion as INFORMED in Impower.
Downgrade is a no-op (Postgres can't DROP an enum value).

Revision ID: o9l3h7j1e6f2
Revises: n8k2g6i0d5e1
"""

from alembic import op

revision = "o9l3h7j1e6f2"
down_revision = "n8k2g6i0d5e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_category ADD VALUE IF NOT EXISTS 'PLAN_ADJUSTMENT'")


def downgrade() -> None:
    pass
