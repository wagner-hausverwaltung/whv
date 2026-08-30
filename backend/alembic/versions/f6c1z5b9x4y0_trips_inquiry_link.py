"""Fahrtenbuch — link a trip to an anfragen@ inquiry (ADR-0020, Besichtigung).

A Besichtigung in the offer phase visits an object that is not in the master
data yet, so the trip references the OfferInquiry instead of a property. The
Anfrage derives "besichtigt am …" from its linked trips. SET NULL on inquiry
deletion: the trip (and its Kilometergeld) stays, only the link goes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "f6c1z5b9x4y0"
down_revision = "e5b0y4a8w3x9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trips",
        sa.Column(
            "inquiry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("offer_inquiries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_trips_inquiry_id", "trips", ["inquiry_id"])


def downgrade() -> None:
    op.drop_index("ix_trips_inquiry_id", table_name="trips")
    op.drop_column("trips", "inquiry_id")
