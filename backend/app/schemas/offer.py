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

    art: Literal["WEG", "MV", "SEV"]
    # MV/SEV only: which VDIV-2026 contract variant to render. Verbraucher
    # (private landlords, with Widerrufsbelehrung) is the default; WEG has
    # no variants and ignores this.
    variant: Literal["verbraucher", "unternehmer"] = "verbraucher"
    units: int = Field(ge=1, le=1000)
    start_date: date | None = None
    # Optional explicit contract end date (else start + term - 1 day). When set,
    # a whole-year term is derived for the MV "N Jahren" clause + fee schedule.
    end_date: date | None = None
    term_years: int = Field(default=4, ge=1, le=10)
    # Optional per-unit net rate override (else the standard default applies).
    rate_per_unit_net: Decimal | None = Field(default=None, gt=0, le=10000)
    # Optional override of the headline year-1 monthly net Festverguetung - what
    # the Verwalter sees + can overwrite in the send dialog. Bypasses the
    # units*rate + 270 EUR floor calc; gross + escalator derive from it.
    monthly_fee_net_override: Decimal | None = Field(default=None, gt=0, le=100000)

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
        # An explicit end date must sit after the start (when both are given;
        # an unset start defaults to 1 Jan next year, validated server-side).
        if self.end_date is not None:
            # start_date defaults to 1 Jan next year when omitted — validate the
            # end against that EFFECTIVE start, else a blank-start + past-end
            # request would slip through and print a backwards contract.
            effective_start = self.start_date or date(date.today().year + 1, 1, 1)
            if self.end_date <= effective_start:
                raise ValueError("end_date must be after the contract start")
        # WEG needs only the unit count — the object address is optional. Not
        # every inquiry includes one, and a blank address line simply renders
        # empty on the contract.
        if self.art in ("MV", "SEV"):
            # The 2026 contract carries the Eigentümer block on page 1; a
            # salutation is no longer needed (the VDIV contract has no cover
            # letter — the offer email is the cover).
            missing = [
                n
                for n in ("recipient_name", "recipient_street", "recipient_plz_city")
                if not getattr(self, n)
            ]
            if missing:
                raise ValueError(f"{self.art} offer requires: {', '.join(missing)}")
            if not self.objects:
                raise ValueError(f"{self.art} offer requires at least one object")
            if len(self.objects) > 3:
                raise ValueError(f"{self.art} offer supports at most 3 objects")
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
    """An inbound anfragen@ inquiry, for the Admin review queue. Lean by design —
    the heavy fields (raw email body, note, error) live on the detail response so
    the list payload stays small."""

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
    # Lightweight flags the list needs for per-row actions (download/reminder)
    # without pulling the full detail. generated_offer_filename gates the
    # re-download button; the reminder fields gate/annotate the reminder button.
    generated_offer_filename: str | None = None
    last_reminder_at: datetime | None = None
    reminder_count: int = 0


class OfferInquiryDetailResponse(OfferInquiryResponse):
    """Single-inquiry detail — adds the full email body, the shared note, the
    error detail (when FAILED), and the sent message id. Returned by the GET
    detail endpoint and by the note / reminder mutations."""

    body: str
    review_note: str | None
    error: str | None
    sent_message_id: str | None


class OfferInquiryNoteUpdate(BaseModel):
    """Set the shared free-text note on one inquiry (visible to every Verwalter
    in the org). Empty string / null clears it."""

    review_note: str | None = Field(default=None, max_length=5000)


class OfferInquiryFieldsUpdate(BaseModel):
    """Verwalter corrections to the extracted inquiry fields — e.g. fill in a
    street + number the prospect didn't disclose initially, or fix the unit
    count / type the LLM got wrong. Overwrites the stored values (null clears a
    field), so the list, the send dialog, and a re-extract all see the correction."""

    art: Literal["WEG", "MV", "SEV"] | None = None
    object_address: str | None = Field(default=None, max_length=400)
    units: int | None = Field(default=None, ge=1, le=1000)
    desired_start: date | None = None
