"""Fahrtenbuch request/response schemas (ADR-0020)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.types import DecimalAsFloat

Purpose = Literal[
    "BESICHTIGUNG",
    "ETV",
    "HANDWERKERTERMIN",
    "EIGENTUEMERTERMIN",
    "BUERO",
    "SONSTIGES",
    "PRIVAT",
]
Source = Literal["AUTO", "MANUAL", "CARPLAY"]

_LAT = Field(default=None, ge=-90, le=90)
_LNG = Field(default=None, ge=-180, le=180)


class TripStartRequest(BaseModel):
    """Manual Start (or CarPlay connect): opens a RUNNING trip."""

    started_at: datetime | None = None
    start_lat: Decimal | None = _LAT
    start_lng: Decimal | None = _LNG
    source: Source = "MANUAL"
    # Besichtigung of a prospect (anfragen@ inquiry) — see Trip.inquiry_id.
    inquiry_id: uuid.UUID | None = None


class TripCompleteRequest(BaseModel):
    """One-shot upload of a finished trip — the normal path for automatic
    detection, where the phone only talks to us once the drive is over."""

    started_at: datetime
    ended_at: datetime
    start_lat: Decimal | None = _LAT
    start_lng: Decimal | None = _LNG
    end_lat: Decimal | None = _LAT
    end_lng: Decimal | None = _LNG
    distance_m: int = Field(ge=0, le=2_000_000)
    route_polyline: str | None = Field(default=None, max_length=200_000)
    source: Source = "AUTO"
    # Optional: the driver may already have confirmed on the phone.
    purpose: Purpose | None = None
    property_id: uuid.UUID | None = None
    inquiry_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _ordered(self) -> TripCompleteRequest:
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        return self


class TripUpdateRequest(BaseModel):
    """End a RUNNING trip and/or confirm purpose + property. Every field is
    optional; only supplied ones change. Confirming `purpose` moves the trip
    to CONFIRMED."""

    ended_at: datetime | None = None
    end_lat: Decimal | None = _LAT
    end_lng: Decimal | None = _LNG
    distance_m: int | None = Field(default=None, ge=0, le=2_000_000)
    route_polyline: str | None = Field(default=None, max_length=200_000)
    purpose: Purpose | None = None
    # Explicit None clears the property (e.g. Büro) — tracked via `model_fields_set`.
    property_id: uuid.UUID | None = None
    # Same semantics: explicit None unlinks the inquiry.
    inquiry_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None = None
    property_id: uuid.UUID | None = None
    property_name: str | None = None
    # Linked anfragen@ inquiry (Besichtigung of a prospect) + its object
    # address for display — the trip has no property in that case.
    inquiry_id: uuid.UUID | None = None
    inquiry_address: str | None = None
    # Auslagen-Rechnung this trip is billed on (None = not billed yet).
    invoice_id: uuid.UUID | None = None
    status: str
    source: str
    purpose: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    # JSON numbers, not Decimal→string — the iOS client decodes Double.
    start_lat: DecimalAsFloat | None = None
    start_lng: DecimalAsFloat | None = None
    end_lat: DecimalAsFloat | None = None
    end_lng: DecimalAsFloat | None = None
    distance_m: int | None = None
    distance_km: Decimal
    route_polyline: str | None = None
    rate_cents_per_km: int
    amount_cents: int
    note: str | None = None


class TripSummary(BaseModel):
    """Totals for the admin list's current filter."""

    trips: int
    distance_m: int
    amount_cents: int
    # Billable subset (excludes PRIVAT / zero-distance) — what goes to the WEGs.
    billable_trips: int
    billable_distance_m: int


class TripPropertyTotal(BaseModel):
    """Auslagen per property for the filtered period."""

    property_id: uuid.UUID | None
    property_name: str
    trips: int
    distance_m: int
    amount_cents: int


class AdminTripListResponse(BaseModel):
    items: list[TripResponse]
    summary: TripSummary
    by_property: list[TripPropertyTotal]


class DelayNoticeRequest(BaseModel):
    """ "Ich verspäte mich" from the car: one tap, we e-mail the contact."""

    contact_id: uuid.UUID
    minutes: int = Field(ge=5, le=180)
    # Current position, if the phone has one — becomes a Maps link so the
    # recipient can see where the Verwalter is.
    lat: Decimal | None = _LAT
    lng: Decimal | None = _LNG
    property_id: uuid.UUID | None = None


class DelayNoticeResponse(BaseModel):
    sent: bool
    to: str | None
    detail: str


# --- Auslagen-Rechnung je Objekt (Phase 5) ------------------------------------


class BillableTripsResponse(BaseModel):
    """What the Verwalter sees before creating an invoice: every confirmed,
    not-yet-billed, non-private trip of the property up to `until`, plus the
    default rule for this property type (pre-selected ids + rate + clause)."""

    items: list[TripResponse]
    suggested_trip_ids: list[uuid.UUID]
    rate_cents_per_km: int
    legal_basis: str
    rule_hint: str


class TripInvoiceCreate(BaseModel):
    property_id: uuid.UUID
    trip_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    rate_cents_per_km: int = Field(ge=1, le=500)
    vat_percent: Decimal = Field(default=Decimal("19"), ge=0, le=100)
    issued_on: date | None = None
    legal_basis: str | None = Field(default=None, max_length=600)
    note: str | None = Field(default=None, max_length=1000)


class TripInvoiceLine(BaseModel):
    trip_id: uuid.UUID
    date: date
    purpose: str | None
    distance_m: int
    amount_cents: int
    note: str | None = None


class TripInvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    property_name: str | None = None
    number: str
    issued_on: date
    period_from: date
    period_to: date
    rate_cents_per_km: int
    vat_percent: DecimalAsFloat
    trip_count: int
    distance_m: int
    net_cents: int
    vat_cents: int
    gross_cents: int
    legal_basis: str | None = None
    note: str | None = None
    created_at: datetime
    # Only the most recent invoice of the org may be cancelled (no gaps).
    cancellable: bool = False
