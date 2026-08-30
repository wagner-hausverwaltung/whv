"""Fahrtenbuch — one row per Dienstfahrt of a Verwalter (ADR-0020).

The car is a PRIVATE car (owned by Luis Wagner, driven by the Verwalter), so
this is a Kilometergeld log (0,30 EUR/km reimbursement to the owner, settings
trip_payee_*) plus the contract-dependent Auslagen-Rechnung to the property
(see trip_invoice.py), not a Finanzamt-Fahrtenbuch for a Firmenwagen: GPS
distance is sufficient, no odometer, no tamper-proofing beyond the audit log.

Lifecycle: RUNNING (started, phone is tracking) → OPEN (ended, purpose and/or
property still to confirm) → CONFIRMED. Most trips arrive already complete via
one upload from the phone after automatic detection; RUNNING only exists for
manual Start/Stop and the future CarPlay trigger.

`purpose` / `source` / `status` are free-form Text with StrEnum validation at
the schema layer — same evolvability choice as offer_inquiries.status: adding
a purpose must not need a migration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class TripStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"


class TripSource(enum.StrEnum):
    AUTO = "AUTO"  # motion/location detection on the phone
    MANUAL = "MANUAL"  # Start/Stop tapped by the driver
    CARPLAY = "CARPLAY"  # CarPlay connect/disconnect (once the entitlement lands)


class TripPurpose(enum.StrEnum):
    BESICHTIGUNG = "BESICHTIGUNG"
    ETV = "ETV"
    HANDWERKERTERMIN = "HANDWERKERTERMIN"
    EIGENTUEMERTERMIN = "EIGENTUEMERTERMIN"
    BUERO = "BUERO"
    SONSTIGES = "SONSTIGES"
    # Kept in the log so the day is complete, but never reimbursed or billed.
    PRIVAT = "PRIVAT"


class Trip(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The WEG/MV the trip was for — drives the Auslagen per property. NULL for
    # Büro/privat and until the driver confirms the app's suggestion.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )
    # Besichtigung of a PROSPECTIVE object: an anfragen@ inquiry in the offer
    # phase has no property in the master data yet, so the trip points at the
    # inquiry instead. The Anfrage derives "besichtigt am …" from these rows;
    # the Kilometergeld is WHV's own acquisition cost (no WEG to bill).
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offer_inquiries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Set once the trip is on an Auslagen-Rechnung to the property (Phase 5);
    # billed trips are excluded from the next invoice's selection.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trip_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(Text, nullable=False, default=TripStatus.RUNNING.value)
    source: Mapped[str] = mapped_column(Text, nullable=False, default=TripSource.MANUAL.value)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    start_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    start_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    end_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    end_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    # GPS distance in metres as measured by the phone; the backend never
    # re-derives it from the polyline (the phone has the full-resolution track).
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Google-encoded polyline of the driven route, for the admin map. Optional:
    # the driver may switch route storage off and keep only start/end.
    route_polyline: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Snapshot of the Kilometersatz at the time of the trip, so a later rate
    # change never rewrites historic reimbursements.
    rate_cents_per_km: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_trips_org_user_started", "organization_id", "user_id", "started_at"),
    )

    @property
    def distance_km(self) -> Decimal:
        return (Decimal(self.distance_m or 0) / 1000).quantize(Decimal("0.1"))

    @property
    def is_billable(self) -> bool:
        """Private trips and trips without a distance earn nothing."""
        return self.purpose != TripPurpose.PRIVAT.value and bool(self.distance_m)

    @property
    def amount_cents(self) -> int:
        """Kilometergeld for this trip, rounded to the cent."""
        if not self.is_billable:
            return 0
        return round(Decimal(self.distance_m or 0) / 1000 * self.rate_cents_per_km)
