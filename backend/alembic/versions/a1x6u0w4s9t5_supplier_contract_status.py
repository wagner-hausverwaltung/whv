"""Versorgungsverträge — manual lifecycle status (AKTIV/GEKUENDIGT/BEENDET)."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1x6u0w4s9t5"
down_revision = "z0w5t9v3r8s4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplier_contracts",
        sa.Column("status", sa.Text(), nullable=False, server_default="AKTIV"),
    )


def downgrade() -> None:
    op.drop_column("supplier_contracts", "status")
