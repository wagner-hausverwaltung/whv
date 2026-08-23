"""Auslagen-Rechnung Fahrtkosten — one invoice from WHV to a property (WEG /
MV / SEV) for a set of logged trips (ADR-0020, Phase 5).

What WHV may bill is contract-dependent and NOT the internal Kilometergeld
(0,30 EUR/km to the driver):
  * WEG-Verwaltervertrag (WHV-Muster 2025) § 8.3.2 — Fahrtkosten only for
    Beirats-/Eigentümerversammlungen outside Kreis Stuttgart, at the tax
    rate (currently 0,42 EUR/km);
  * VDIV-2026 MV/SEV § 5.3/5.4 — Verwaltung↔Objekt trips are covered by the
    monthly Auslagen-Pauschale; other trips at 0,50 EUR/km.
So an invoice is always a Verwalter's explicit selection of trips + rate; the
service only pre-selects per the default rule. Invoices are immutable: the
lines are a JSON snapshot (later trip edits don't rewrite a sent invoice), the
number is sequential per org and year, and only the most recent invoice can
be cancelled (no gaps in the sequence). Trips point at their invoice so they
are never billed twice.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class TripInvoice(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "trip_invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # "WHV-FK-2026-0001" — sequential per org + year (see services.trip_invoice).
    number: Mapped[str] = mapped_column(Text, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)

    rate_cents_per_km: Mapped[int] = mapped_column(Integer, nullable=False)
    vat_percent: Mapped[Any] = mapped_column(Numeric(4, 2), nullable=False, default=19)
    trip_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    net_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    vat_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Immutable snapshots: invoice lines + recipient block as rendered.
    lines_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    recipient_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # The contract clause printed as the basis of the charge.
    legal_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "number", name="uq_trip_invoices_number"),
    )
