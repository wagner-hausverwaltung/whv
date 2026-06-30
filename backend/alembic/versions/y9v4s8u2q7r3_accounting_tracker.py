"""Jahresabrechnung progress tracker — accounting_cycles + accounting_cycle_stages.

Per-Objekt, per-Wirtschaftsjahr cycle with the 9 fixed stages A–I (all-manual v1).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "y9v4s8u2q7r3"
down_revision = "x8u3r7t1p6q2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounting_cycles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("property_id", "year", name="uq_accounting_cycle_property_year"),
    )
    op.create_table(
        "accounting_cycle_stages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cycle_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounting_cycles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stage_code", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "done_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("cycle_id", "stage_code", name="uq_accounting_stage_cycle_code"),
    )


def downgrade() -> None:
    op.drop_table("accounting_cycle_stages")
    op.drop_table("accounting_cycles")
