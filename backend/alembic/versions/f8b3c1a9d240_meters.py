"""Add `meters` + `meter_readings` — Zähler management (ADR-0016).

A meter is Verwalter-created and attached to a property (optionally a
unit); every property member can submit a reading, optionally with a
photo that the app OCR's to pre-fill the value.

Revision ID: f8b3c1a9d240
Revises: s3p8m2o6k1l7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f8b3c1a9d240"
down_revision = "s3p8m2o6k1l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("meter_number", sa.Text, nullable=False),
        sa.Column(
            "meter_type",
            sa.Enum(
                "STROM",
                "GAS",
                "WASSER",
                "WARMWASSER",
                "WAERME",
                "SONSTIGES",
                name="meter_type",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("location", sa.Text, nullable=True),
        sa.Column("unit_label", sa.Text, nullable=True),
        sa.Column("installation_date", sa.Date, nullable=True),
        sa.Column("calibration_valid_until", sa.Date, nullable=True),
        sa.Column("supplier_name", sa.Text, nullable=True),
        sa.Column("supplier_email", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_meters_organization_id", "meters", ["organization_id"])
    op.create_index("ix_meters_property_id", "meters", ["property_id"])
    op.create_index("ix_meters_unit_id", "meters", ["unit_id"])
    op.create_index("ix_meters_org_property", "meters", ["organization_id", "property_id"])

    op.create_table(
        "meter_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "meter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(14, 3), nullable=False),
        sa.Column("read_on", sa.Date, nullable=False),
        sa.Column(
            "source",
            sa.Enum("MANUAL", "OCR", name="meter_reading_source"),
            nullable=False,
            server_default="MANUAL",
        ),
        sa.Column("ocr_raw", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("photo_storage_url", sa.Text, nullable=True),
        sa.Column("photo_mime_type", sa.Text, nullable=True),
        sa.Column(
            "reported_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forwarded_to", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_meter_readings_meter_id", "meter_readings", ["meter_id"])
    op.create_index("ix_meter_readings_meter_read_on", "meter_readings", ["meter_id", "read_on"])


def downgrade() -> None:
    op.drop_index("ix_meter_readings_meter_read_on", "meter_readings")
    op.drop_index("ix_meter_readings_meter_id", "meter_readings")
    op.drop_table("meter_readings")
    op.drop_index("ix_meters_org_property", "meters")
    op.drop_index("ix_meters_unit_id", "meters")
    op.drop_index("ix_meters_property_id", "meters")
    op.drop_index("ix_meters_organization_id", "meters")
    op.drop_table("meters")
    sa.Enum(name="meter_reading_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="meter_type").drop(op.get_bind(), checkfirst=True)
