"""Fahrtenbuch — trips table + property coordinates (ADR-0020).

One row per Dienstfahrt of a Verwalter (private car, Kilometergeld 0,30 EUR/km
+ Auslagen per WEG). Properties gain lat/lng so the phone can suggest the
destination property from the trip's end position.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "e5b0y4a8w3x9"
down_revision = "d4a9x3z7v2w8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("lat", sa.Numeric(9, 6), nullable=True))
    op.add_column("properties", sa.Column("lng", sa.Numeric(9, 6), nullable=True))

    op.create_table(
        "trips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="RUNNING"),
        sa.Column("source", sa.Text(), nullable=False, server_default="MANUAL"),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("start_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("end_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("end_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("route_polyline", sa.Text(), nullable=True),
        sa.Column("rate_cents_per_km", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"])
    op.create_index(
        "ix_trips_org_user_started", "trips", ["organization_id", "user_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_trips_org_user_started", table_name="trips")
    op.drop_index("ix_trips_user_id", table_name="trips")
    op.drop_table("trips")
    op.drop_column("properties", "lng")
    op.drop_column("properties", "lat")
