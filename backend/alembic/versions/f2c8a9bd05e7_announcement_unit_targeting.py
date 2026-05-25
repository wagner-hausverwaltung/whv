"""announcement_units junction table

Optional per-unit recipient narrowing on top of the role audience
filter. When the set is empty (no rows for this announcement), fan-out
follows the existing property-wide-by-role behaviour. When non-empty,
the resolved recipient set is intersected with "users on a contract
that covers one of the listed units" — so e.g. an admin can send a
Mitteilung only to Mietern in unit 3a + 4b.

Revision ID: f2c8a9bd05e7
Revises: e3f8b2cd5a91
Create Date: 2026-05-25 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2c8a9bd05e7"
down_revision: str | Sequence[str] | None = "e3f8b2cd5a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "announcement_units",
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("announcement_id", "unit_id"),
    )
    # Reverse-lookup: "which announcements target this unit?" — not
    # used by core flow but handy for debugging + future reporting.
    op.create_index(
        "ix_announcement_units_unit_id",
        "announcement_units",
        ["unit_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_announcement_units_unit_id",
        table_name="announcement_units",
    )
    op.drop_table("announcement_units")
