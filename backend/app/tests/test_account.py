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
        sort: str = "postDate",
        order: str = "DESC",
    ) -> dict[str, Any]:
        return {"content": self._postings}


async def test_load_account_resolves_leaf_and_sums_balance() -> None:
    client = _FakeClient(
        accounts=[
            {"id": 5, "leaf": False, "name": "Sammelkonto"},
            {"id": 10, "leaf": True, "accountHrId": "D-1000", "name": "Müller"},
        ],
        postings=[
            {"postDate": "2026-01-15", "bookingText": "Hausgeld Januar", "amount": -250.0},
            {"postDate": "2026-01-31", "bookingText": "Zahlung", "amount": 250.0},
            {"postDate": "2026-02-15", "bookingText": "Hausgeld Februar", "amount": -250.0},
        ],
    )
    res = await load_my_account(client, property_impower_id=1, contact_id_impower=999)

    # Picked the leaf account, scoped by CONTACT source.
    assert res.account_id == 10
    assert res.account_hr_id == "D-1000"
    assert client.account_calls[0]["source_types"] == ["CONTACT"]
    assert client.account_calls[0]["source_ids"] == [999]
    # Balance = signed sum of all bookings.
    assert res.balance == Decimal("-250.0")
    assert len(res.bookings) == 3
    assert res.bookings[0].booking_text == "Hausgeld Januar"


async def test_load_account_empty_when_no_contact_account() -> None:
    client = _FakeClient(accounts=[], postings=[])
    res = await load_my_account(client, property_impower_id=1, contact_id_impower=999)
    assert res.account_id is None
    assert res.balance is None
    assert res.bookings == []
