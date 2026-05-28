"""Hausgeld-Anpassung notification: only INFORMED suggestions notify
the owner on the contract, idempotently (Redis dedupe)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import UserRole
from app.services.plan_adjustment_notify import notify_plan_adjustments
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)


def _uid() -> int:
    return uuid.uuid4().int % 9_000_000_000_000_000


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class _FakeImpowerClient:
    """Returns suggestions keyed by contract id; empty for any other
    contract so the global poll stays deterministic in the shared DB."""

    def __init__(self, by_contract: dict[int, list[dict[str, Any]]]) -> None:
        self._by_contract = by_contract

    async def get_plan_adjustment_suggestions(
        self, *, contract_id: int, page: int = 0, size: int = 100
    ) -> dict[str, Any]:
        return {"content": self._by_contract.get(contract_id, [])}


class _RecordingEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append(to)
        return "rec-id"


async def test_informed_suggestion_notifies_contract_owner(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner = _uid()
    contract_imp = _uid()
    sid = _uid()
    _, owner_email, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=c_owner,
        contract_impower_id=contract_imp,
    )

    suggestions = [
        {
            "id": sid,
            "ownerCommunicationState": "INFORMED",
            "previousCost": 250.0,
            "amount": 30.0,
            "targetDate": "2026-07-01",
        },
        # A TODO suggestion on the same contract must NOT notify.
        {
            "id": _uid(),
            "ownerCommunicationState": "TODO",
            "previousCost": 250.0,
            "amount": 99.0,
            "targetDate": "2026-08-01",
        },
    ]
    client = _FakeImpowerClient({contract_imp: suggestions})
    redis: Any = _FakeRedis()
    recorder = _RecordingEmail()

    async with sm() as s:
        n1 = await notify_plan_adjustments(s, client=client, redis=redis, email_client=recorder)

    assert n1 == 1  # only the INFORMED one
    assert owner_email in recorder.sent

    # Idempotent: the suggestion id is marked → a second poll is silent.
    recorder2 = _RecordingEmail()
    async with sm() as s:
        n2 = await notify_plan_adjustments(s, client=client, redis=redis, email_client=recorder2)
    assert n2 == 0
    assert recorder2.sent == []
