"""Request schema for the manual offer (Angebot) generator (ADR-0019)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OfferGenerateRequest(BaseModel):
    """Inputs the Verwalter fills in the "Angebot erstellen" form.

    Shared fields drive the pricing engine; the WEG / MV blocks supply the
    per-customer text. Unset ``start_date`` defaults to 1 Jan next year and
    ``offer_date`` to today (resolved server-side so tests can pin them).
    """

    art: Literal["WEG", "MV"]
    units: int = Field(ge=1, le=1000)
    start_date: date | None = None
    term_years: int = Field(default=4, ge=1, le=10)
    # Optional per-unit net rate override (else the standard default applies).
    rate_per_unit_net: Decimal | None = Field(default=None, gt=0, le=10000)

    # --- WEG ---
    object_street: str | None = Field(default=None, max_length=200)
    object_plz_city: str | None = Field(default=None, max_length=200)

    # --- MV ---
    offer_date: date | None = None
    recipient_name: str | None = Field(default=None, max_length=200)
    recipient_street: str | None = Field(default=None, max_length=200)
    recipient_plz_city: str | None = Field(default=None, max_length=200)
    salutation: str | None = Field(default=None, max_length=200)
    objects: list[str] | None = None
    representative_name: str | None = Field(default=None, max_length=200)
    representative_street: str | None = Field(default=None, max_length=200)
    representative_plz_city: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_per_art_fields(self) -> OfferGenerateRequest:
        # WEG needs only the unit count — the object address is optional. Not
        # every inquiry includes one, and a blank address line simply renders
        # empty on the contract.
        if self.art == "MV":
            missing = [
                n
                for n in ("recipient_name", "recipient_street", "recipient_plz_city", "salutation")
                if not getattr(self, n)
            ]
            if missing:
                raise ValueError(f"MV offer requires: {', '.join(missing)}")
            if not self.objects:
                raise ValueError("MV offer requires at least one object")
            if len(self.objects) > 3:
                raise ValueError("MV offer supports at most 3 objects")
        return self


class OfferSettingsResponse(BaseModel):
    """Org-level anfragen@ settings shown on the Admin review queue."""

    auto_send_enabled: bool


class OfferSettingsUpdate(BaseModel):
    """Toggle the org's "Auto-Modus" (auto-approve + email inbound offers)."""

    auto_send_enabled: bool


class OfferLeadStatusUpdate(BaseModel):
    """Set the manual sales status of one inquiry from the review queue."""

    lead_status: Literal["OPEN", "ON_HOLD", "ACCEPTED", "DECLINED"]


class OfferInquiryResponse(BaseModel):
    """An inbound anfragen@ inquiry, for the Admin review queue."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_email: str
    sender_name: str | None
    subject: str
    status: str
    lead_status: str
    art: str | None
    object_address: str | None
    units: int | None
    desired_start: date | None
    confidence: float | None
    sent_at: datetime | None
    created_at: datetime
