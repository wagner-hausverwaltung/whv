"""Assemble an owner's Hausgeldkonto from Impower accounts + postings.

We don't mirror accounts locally (high churn, read on tab-open). Given a
property + the caller's Impower contact id, we find their CONTACT-source
account on that property, pull its bookings, and sum them into a signed
balance. Presentation stays neutral (see schemas/account.py).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.account import HausgeldAccountResponse, PostingItemResponse

# Pull a generous page so the summed balance covers a full account
# history — typical owner Hausgeld accounts have far fewer postings than
# this in a year.
_POSTINGS_PAGE_SIZE = 1000


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
    """Impower paged bodies wrap rows in `content`; be defensive about a
    bare list too."""
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        items = raw.get("content")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


_EMPTY = HausgeldAccountResponse(
    account_id=None, account_hr_id=None, name=None, balance=None, bookings=[]
)


async def load_my_account(
    client: object,
    *,
    property_impower_id: int,
    contract_impower_ids: list[int],
) -> HausgeldAccountResponse:
    """Resolve the caller's Hausgeld account on a property, sum its
    bookings into a balance, and return the booking list (newest first).
    Returns an empty shell when the owner has no such account.

    The owner's accounts are sourced by CONTRACT in Impower (sourceType=
    CONTRACT, keyed by the owner's contract id) — NOT CONTACT, which only
    holds vendor / Kreditoren accounts. Each owner contract carries ~10
    sub-accounts (Hausgeld, Rücklage, Sonderumlage, Mahngebühren, …); the
    regular Hausgeld debitor is the leaf named 'Hausgeld …', which is what
    'Mein Hausgeldkonto' shows."""
    if not contract_impower_ids:
        return _EMPTY
    accounts_raw = await client.get_accounts(  # type: ignore[attr-defined]
        property_id=property_impower_id,
        source_ids=contract_impower_ids,
        source_types=["CONTRACT"],
    )
    accounts = _content(accounts_raw)
    if not accounts:
        return _EMPTY

    # The regular Hausgeld debitor ("Hausgeld 4 - Luis Wagner"); fall back to
    # the first leaf if Impower ever renames it.
    account = (
        next(
            (
                a
                for a in accounts
                if a.get("leaf")
                and isinstance(a.get("name"), str)
                and a["name"].startswith("Hausgeld")
            ),
            None,
        )
        or next((a for a in accounts if a.get("leaf")), None)
        or accounts[0]
    )
    account_id = account.get("id")
    if not isinstance(account_id, int):
        return _EMPTY

    postings_raw = await client.get_posting_items(  # type: ignore[attr-defined]
        account_ids=[account_id], size=_POSTINGS_PAGE_SIZE
    )
    rows = _content(postings_raw)

    balance = Decimal("0")
    bookings: list[PostingItemResponse] = []
    for row in rows:
        amount = _dec(row.get("amount"))
        if amount is not None:
            balance += amount
        bookings.append(
            PostingItemResponse(
                post_date=_str(row.get("postDate")),
                booking_text=_str(row.get("bookingText")),
                amount=amount,
            )
        )

    return HausgeldAccountResponse(
        account_id=account_id,
        account_hr_id=_str(account.get("accountHrId")),
        name=_str(account.get("name")),
        balance=balance,
        bookings=bookings,
    )
