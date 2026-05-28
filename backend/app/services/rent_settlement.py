"""Project Impower's RentSettlementDto down to the owner-facing
Mietabrechnung rows. Pure: takes a client + the caller's contract ids,
returns the narrow response list."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.rent_settlement import RentSettlementResponse


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _content(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        items = raw.get("content")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


async def load_my_rent_settlements(
    client: object,
    *,
    contract_impower_ids: list[int],
) -> list[RentSettlementResponse]:
    """Mietabrechnung rows for the caller's owner contract(s). Empty
    when there are no contracts (e.g. a WEG property, a tenant)."""
    if not contract_impower_ids:
        return []
    raw = await client.get_rent_settlements(contract_ids=contract_impower_ids)  # type: ignore[attr-defined]
    out: list[RentSettlementResponse] = []
    for row in _content(raw):
        out.append(
            RentSettlementResponse(
                period_from=_str(row.get("timeFrameFrom")),
                period_until=_str(row.get("timeFrameUntil")),
                due_date=_str(row.get("dueDate")),
                rent_income=_dec(row.get("rentIncomeAmount")),
                payout=_dec(row.get("payoutAmount")),
                balance=_dec(row.get("balanceAmount")),
                state=_str(row.get("exchangeState")),
            )
        )
    return out
