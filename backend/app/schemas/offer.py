"""Request schema for the manual offer (Angebot) generator (ADR-0017)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
        if self.art == "WEG":
            missing = [
                n for n in ("object_street", "object_plz_city") if not getattr(self, n)
            ]
            if missing:
                raise ValueError(f"WEG offer requires: {', '.join(missing)}")
        else:  # MV
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
