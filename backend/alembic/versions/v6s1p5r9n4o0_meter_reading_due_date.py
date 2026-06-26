"""Add meters.reading_due_date (Zählerstand reminder for the activity feed).

Nullable target date for the next reading. The activity feed shows a
"Zählerstand erfassen" reminder while this is set and no reading exists on/after
it. Independent of calibration_valid_until (Eichfrist).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v6s1p5r9n4o0"
down_revision = "u5r0o4q8m3n9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meters", sa.Column("reading_due_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("meters", "reading_due_date")
