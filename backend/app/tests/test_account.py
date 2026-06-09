"""Hausgeldkonto assembly: account resolution + balance sum from
Impower accounts + posting-items (pure service, fake client)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.account import load_my_account


class _FakeClient:
    def __init__(self, accounts: list[dict[str, Any]], postings: list[dict[str, Any]]) -> None:
        self._accounts = accounts
        self._postings = postings
        self.account_calls: list[dict[str, Any]] = []

    async def get_accounts(
        self,
        *,
        property_id: int,
        source_ids: list[int] | None = None,
        source_types: list[str] | None = None,
        page: int = 0,
        size: int = 100,
    ) -> dict[str, Any]:
        self.account_calls.append(
            {"property_id": property_id, "source_ids": source_ids, "source_types": source_types}
        )
        return {"content": self._accounts}

    async def get_posting_items(
        self,
        *,
        account_ids: list[int],
        page: int = 0,
        size: int = 100,
    ) -> dict[str, Any]:
        # Impower's /posting-items 500s on sort/order params (no longer sent);
        # rows come back unsorted, so the service must order them itself.
        return {"content": self._postings}


async def test_load_account_picks_hausgeld_and_sums_balance() -> None:
    # Owner contract accounts: a parent group + the Soll-Rücklage leaf +
    # the Hausgeld debitor leaf. We must pick the Hausgeld one (not the
    # Rücklage, not the parent), querying by CONTRACT source.
    client = _FakeClient(
        accounts=[
            {"id": 5, "leaf": False, "name": "4 - Luis Wagner"},
            {
                "id": 7,
                "leaf": True,
                "accountHrId": "2000/4/2/0",
                "name": "Soll-Rücklage 4 - Luis Wagner",
            },
            {"id": 10, "leaf": True, "accountHrId": "2000/4/1", "name": "Hausgeld 4 - Luis Wagner"},
        ],
        postings=[
            {"postDate": "2026-01-15", "bookingText": "Hausgeld Januar", "amount": -250.0},
            {"postDate": "2026-01-31", "bookingText": "Zahlung", "amount": 250.0},
            {"postDate": "2026-02-15", "bookingText": "Hausgeld Februar", "amount": -250.0},
        ],
    )
    res = await load_my_account(client, property_impower_id=1, contract_impower_ids=[999])

    # Queried by CONTRACT (owner accounts), not CONTACT (vendors).
    assert client.account_calls[0]["source_types"] == ["CONTRACT"]
    assert client.account_calls[0]["source_ids"] == [999]
    # Picked the Hausgeld debitor leaf — not the Rücklage leaf, not the parent.
    assert res.account_id == 10
    assert res.account_hr_id == "2000/4/1"
    # Balance = signed sum of all bookings.
    assert res.balance == Decimal("-250.0")
    assert len(res.bookings) == 3
    # Service orders postings newest-first in Python (Impower can't sort them
    # server-side without 500ing), even though the fake returns them ascending.
    assert [b.post_date for b in res.bookings] == ["2026-02-15", "2026-01-31", "2026-01-15"]
    assert res.bookings[0].booking_text == "Hausgeld Februar"


async def test_load_account_empty_when_no_contract_or_account() -> None:
    # No contracts → empty shell, without even calling Impower.
    res = await load_my_account(
        _FakeClient(accounts=[], postings=[]), property_impower_id=1, contract_impower_ids=[]
    )
    assert res.account_id is None
    assert res.balance is None
    assert res.bookings == []
    # Contracts but Impower returns no matching accounts → empty too.
    res2 = await load_my_account(
        _FakeClient(accounts=[], postings=[]), property_impower_id=1, contract_impower_ids=[999]
    )
    assert res2.account_id is None
