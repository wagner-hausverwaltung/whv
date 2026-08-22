"""Fahrtenbuch request/response schemas (ADR-0020)."""

from __future__ import annotations

import uuid
from datetime import datetime
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
    note: str | None = Field(default=None, max_length=2000)


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None = None
    property_id: uuid.UUID | None = None
    property_name: str | None = None
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
