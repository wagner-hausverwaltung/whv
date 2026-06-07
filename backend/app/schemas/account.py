"""Schemas for the owner Hausgeldkonto view (/me/properties/{id}/account).

Deliberately neutral: we expose the signed `balance` (sum of bookings)
without a Guthaben/Forderung interpretation until the sign convention is
confirmed against real Impower data on staging — showing an owner the
wrong direction on their own account would be a trust-breaking bug.
"""

from pydantic import BaseModel

from app.schemas.types import DecimalAsFloat


class PostingItemResponse(BaseModel):
    post_date: str | None
    booking_text: str | None
    amount: DecimalAsFloat | None


class HausgeldAccountResponse(BaseModel):
    # Null when the owner has no CONTACT account on this property (e.g. a
    # Verwalter, or a property where they hold no Hausgeld account).
    account_id: int | None
    account_hr_id: str | None
    name: str | None
    # Signed sum of all fetched bookings. Neutral — the client labels it
    # "Saldo" without a debt/credit claim for now.
    balance: DecimalAsFloat | None
    bookings: list[PostingItemResponse]
