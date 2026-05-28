"""MV-owner Mietabrechnung projection (pure service, fake client)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.rent_settlement import load_my_rent_settlements


class _FakeClient:
    def __init__(self, settlements: list[dict[str, Any]]) -> None:
        self._settlements = settlements
        self.calls: list[list[int]] = []

    async def get_rent_settlements(
        self, *, contract_ids: list[int], page: int = 0, size: int = 100
    ) -> dict[str, Any]:
        self.calls.append(contract_ids)
        return {"content": self._settlements}


async def test_maps_settlement_fields() -> None:
    client = _FakeClient(
        [
            {
                "timeFrameFrom": "2026-01-01",
                "timeFrameUntil": "2026-03-31",
                "dueDate": "2026-04-15",
                "rentIncomeAmount": 3000.0,
                "payoutAmount": 2400.0,
                "balanceAmount": 500.0,
                "exchangeState": "DONE",
            }
        ]
    )
    res = await load_my_rent_settlements(client, contract_impower_ids=[42])
    assert client.calls == [[42]]
    assert len(res) == 1
    assert res[0].rent_income == Decimal("3000.0")
    assert res[0].payout == Decimal("2400.0")
    assert res[0].period_from == "2026-01-01"
    assert res[0].state == "DONE"


async def test_empty_when_no_contracts() -> None:
    client = _FakeClient([{"rentIncomeAmount": 1.0}])
    res = await load_my_rent_settlements(client, contract_impower_ids=[])
    assert res == []
    assert client.calls == []  # never hit the API
