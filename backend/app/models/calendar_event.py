"""Liegenschafts-Kalender events (ADR-0018).

Verwalter-created per-property events — primarily recurring-duty assignments
(Winterdienst, Kehrwoche) handed to an owner, plus generic Termine. ETV dates
are NOT stored here; they're derived live from `etv_assemblies` when the
calendar is assembled, so they never drift from the assembly record.

v1 stores discrete entries (a date or a date range). A weekly auto-rotation
generator for Kehrwoche is a possible later enhancement.
"""

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class CalendarEventType(enum.StrEnum):
    WINTERDIENST = "WINTERDIENST"
    KEHRWOCHE = "KEHRWOCHE"
    TERMIN = "TERMIN"  # generic appointment / note


class CalendarEvent(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[CalendarEventType] = mapped_column(
        Enum(CalendarEventType, name="calendar_event_type"),
        nullable=False,
    )
    # Free-text label; defaulted from the type when the Verwalter leaves it
    # blank (e.g. "Winterdienst").
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    # NULL = single day; set = inclusive range (e.g. a Kehrwoche week).
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The responsible owner. `assigned_user_id` lets the portal/app highlight
    # "your duty" for a logged-in owner; `assigned_label` is the human name
    # (owners without an account, a unit, or an external party).
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Month query: a property's events within a date window.
        Index("ix_calendar_events_property_start", "property_id", "starts_on"),
        Index("ix_calendar_events_org_property", "organization_id", "property_id"),
    )
