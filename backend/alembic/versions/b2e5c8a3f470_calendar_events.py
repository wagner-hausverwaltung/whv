"""Add `calendar_events` — Liegenschafts-Kalender (ADR-0018).

Verwalter-created per-property events (Winterdienst/Kehrwoche assignments +
generic Termine). ETV dates are derived live from etv_assemblies, not stored.

Revision ID: b2e5c8a3f470
Revises: a1d4f7c9e260
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b2e5c8a3f470"
down_revision = "a1d4f7c9e260"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
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
            "event_type",
            sa.Enum("WINTERDIENST", "KEHRWOCHE", "TERMIN", name="calendar_event_type"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("starts_on", sa.Date, nullable=False),
        sa.Column("ends_on", sa.Date, nullable=True),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assigned_label", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
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
    op.create_index("ix_calendar_events_organization_id", "calendar_events", ["organization_id"])
    op.create_index("ix_calendar_events_property_id", "calendar_events", ["property_id"])
    op.create_index("ix_calendar_events_assigned_user_id", "calendar_events", ["assigned_user_id"])
    op.create_index(
        "ix_calendar_events_property_start", "calendar_events", ["property_id", "starts_on"]
    )
    op.create_index(
        "ix_calendar_events_org_property", "calendar_events", ["organization_id", "property_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_events_org_property", "calendar_events")
    op.drop_index("ix_calendar_events_property_start", "calendar_events")
    op.drop_index("ix_calendar_events_assigned_user_id", "calendar_events")
    op.drop_index("ix_calendar_events_property_id", "calendar_events")
    op.drop_index("ix_calendar_events_organization_id", "calendar_events")
    op.drop_table("calendar_events")
    sa.Enum(name="calendar_event_type").drop(op.get_bind(), checkfirst=True)
