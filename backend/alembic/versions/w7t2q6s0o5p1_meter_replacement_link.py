"""Add meters.replaced_at + meters.successor_meter_id (Zählerwechsel).

Every ~6 years a meter is physically swapped. The OLD meter is kept (with its
readings, for Abrechnung) but deactivated; `replaced_at` records the swap date
and `successor_meter_id` self-FKs the OLD meter to the NEW one that replaced it
(ON DELETE SET NULL so deleting the successor doesn't cascade away history).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "w7t2q6s0o5p1"
down_revision = "v6s1p5r9n4o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meters", sa.Column("replaced_at", sa.Date(), nullable=True))
    op.add_column(
        "meters",
        sa.Column("successor_meter_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_meters_successor_meter_id",
        "meters",
        "meters",
        ["successor_meter_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_meters_successor_meter_id", "meters", type_="foreignkey")
    op.drop_column("meters", "successor_meter_id")
    op.drop_column("meters", "replaced_at")
