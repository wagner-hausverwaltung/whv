"""Schema for the MV-property owner Mietabrechnung view
(GET /me/properties/{id}/rent-settlements).

One row per settlement period: what came in (rent income), what was
paid out to the owner, the property account balance, and the period it
covers. Amounts are signed and shown as-is.
"""

from pydantic import BaseModel

from app.schemas.types import DecimalAsFloat


class RentSettlementResponse(BaseModel):
    period_from: str | None
    period_until: str | None
    due_date: str | None
    rent_income: DecimalAsFloat | None
    payout: DecimalAsFloat | None
    balance: DecimalAsFloat | None
    state: str | None
