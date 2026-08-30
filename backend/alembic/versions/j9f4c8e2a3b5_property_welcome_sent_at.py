"""Begrüßungsmitteilung je Objekt — properties.welcome_sent_at.

Marks the moment a property's automatic welcome announcement was created,
so the post-sync phase can find genuinely new objects and never sends twice.

Existing properties are backfilled to now(): they were handed over long ago
and must NOT receive a welcome when the feature ships (otherwise the first
sync after deploy would post into all 25 objects at once).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "j9f4c8e2a3b5"
down_revision = "h8e3b7d1z6a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("welcome_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Everything that exists today counts as "already welcomed".
    op.execute("UPDATE properties SET welcome_sent_at = now()")


def downgrade() -> None:
    op.drop_column("properties", "welcome_sent_at")
