"""Fahrtenbuch — Auslagen-Rechnungen je Objekt (ADR-0020, Phase 5).

trip_invoices: one immutable invoice (snapshot lines, sequential number per
org + year) per property and trip selection; trips.invoice_id marks a trip as
billed so it is never charged twice. SET NULL on invoice deletion (only the
most recent one may be cancelled — enforced in the service, not the schema).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "g7d2a6c0y5z1"
down_revision = "f6c1z5b9x4y0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trip_invoices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("rate_cents_per_km", sa.Integer(), nullable=False),
        sa.Column("vat_percent", sa.Numeric(4, 2), nullable=False, server_default="19"),
        sa.Column("trip_count", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("net_cents", sa.Integer(), nullable=False),
        sa.Column("vat_cents", sa.Integer(), nullable=False),
        sa.Column("gross_cents", sa.Integer(), nullable=False),
        sa.Column("lines_json", JSONB(), nullable=False),
        sa.Column("recipient_json", JSONB(), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "number", name="uq_trip_invoices_number"),
    )
    op.create_index(
        "ix_trip_invoices_org_property", "trip_invoices", ["organization_id", "property_id"]
    )
    op.add_column(
        "trips",
        sa.Column(
            "invoice_id",
            UUID(as_uuid=True),
            sa.ForeignKey("trip_invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_trips_invoice_id", "trips", ["invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_trips_invoice_id", table_name="trips")
    op.drop_column("trips", "invoice_id")
    op.drop_index("ix_trip_invoices_org_property", table_name="trip_invoices")
    op.drop_table("trip_invoices")
