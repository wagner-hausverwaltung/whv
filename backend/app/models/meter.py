"""Zähler (utility meters) + Zählerstände (meter readings).

A `Meter` is created by the Verwalter and attached to a Property. Unit-
specific meters (Wohnungsstrom, Wohnungswasser) carry a `unit_id`;
property-wide meters (Allgemeinstrom, Betriebsstrom, the building's main
Gas/Wärme meter) leave it NULL. Every property member can submit a
`MeterReading` — typically by photographing the meter in the app, where
the photo is OCR'd to pre-fill the value (the user always confirms).

Readings keep the photo (same `local-disk:<suffix>` convention as ticket
attachments) so the Verwalter can later forward value + photo to the
supplier (EnBW etc.). v1 has no in-app supplier send — the
`forwarded_at` / `forwarded_to` columns are reserved for when it lands.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class MeterType(enum.StrEnum):
    """Utility kind. `description` carries the human label (Betriebsstrom,
    Allgemeinstrom, Wohnung 3 …) — this enum is just the broad category so
    the UI can pick an icon + a sensible default unit (kWh / m³)."""

    STROM = "STROM"  # electricity
    GAS = "GAS"
    WASSER = "WASSER"  # cold water
    WARMWASSER = "WARMWASSER"  # hot water
    WAERME = "WAERME"  # Wärmemengenzähler / Heizung
    SONSTIGES = "SONSTIGES"


class MeterReadingSource(enum.StrEnum):
    """How the reading value was entered.

    MANUAL — typed in directly.
    OCR    — pre-filled from a photo by the LLM and (possibly edited then)
             confirmed by the user. We never store an OCR value the user
             didn't confirm, so OCR readings are still user-vouched; the
             distinction is for audit + future accuracy review.
    """

    MANUAL = "MANUAL"
    OCR = "OCR"


class Meter(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "meters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Unit-specific meters carry a unit; property-wide / common meters
    # (Allgemeinstrom, Betriebsstrom, main building meter) leave it NULL.
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Zählernummer as printed on the meter.
    meter_number: Mapped[str] = mapped_column(Text, nullable=False)
    meter_type: Mapped[MeterType] = mapped_column(
        Enum(MeterType, name="meter_type"),
        nullable=False,
    )
    # Free-text label: "Betriebsstrom", "Allgemeinstrom Treppenhaus", …
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where it physically sits: "Keller", "Hausanschlussraum", …
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reading unit ("kWh", "m³"). Defaulted by type at create time when the
    # Verwalter leaves it blank.
    unit_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    installation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Eichfrist — when the meter's calibration expires and it must be swapped.
    calibration_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Next reading due date — drives the "Zählerstand erfassen" reminder in the
    # activity feed. The reminder shows while this is set and no reading has been
    # recorded on/after it; capturing such a reading clears it implicitly.
    reading_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Supplier (EnBW …). Stored on the meter so a future "forward to supplier"
    # send has the address without coupling to a separate Dienstleister model.
    supplier_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft-deactivate when a meter is swapped out — keeps the reading history
    # intact while hiding it from the "report a reading" lists.
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    # Zählerwechsel — a meter is physically swapped roughly every 6 years. The
    # OLD meter is kept (with its readings, for Abrechnung) but deactivated:
    # `replaced_at` records the swap date and `successor_meter_id` links it to
    # the NEW meter that took its place.
    replaced_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    successor_meter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Property-detail "Zähler" tab: list a property's meters.
        Index("ix_meters_org_property", "organization_id", "property_id"),
    )


class MeterReading(Base):
    """A single Zählerstand. Org scope rides via meter → property →
    organization_id; we don't store organization_id directly (mirrors
    TicketMessage) — reading queries always reach in through the meter."""

    __tablename__ = "meter_readings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Numeric (not float) so kWh / m³ figures that feed billing keep exact
    # decimal places. Three fractional digits covers sub-unit water meters.
    value: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    read_on: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[MeterReadingSource] = mapped_column(
        Enum(MeterReadingSource, name="meter_reading_source"),
        nullable=False,
        default=MeterReadingSource.MANUAL,
        server_default=MeterReadingSource.MANUAL.value,
    )
    # Raw text the OCR returned (source=OCR) — kept for audit / accuracy review.
    ocr_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Photo of the meter. Same `local-disk:<suffix>` convention as ticket
    # attachments; NULL when the reading was typed in without a photo.
    photo_storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Reserved for a later in-app "forward to supplier" send. v1 forwards
    # out-of-band (CSV export), so these stay NULL for now.
    forwarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forwarded_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # History render: a meter's readings, newest first.
        Index("ix_meter_readings_meter_read_on", "meter_id", "read_on"),
    )
