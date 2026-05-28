"""Booked-invoice owner notification (richer-webhooks feature).

A BOOKED invoice fans out to the property's active owners; non-BOOKED
states are ignored; former owners are excluded; the Redis dedupe stops
repeated BOOKED redeliveries from re-notifying.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import UserRole
from app.services.invoice_notify import notify_booked_invoice
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
    def __init__(self, invoice: dict[str, Any]) -> None:
        self._invoice = invoice
        self.calls = 0

    async def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        self.calls += 1
        return self._invoice


class _RecordingEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append(to)
        return "rec-id"


_PAST = date(2020, 1, 1)


async def test_booked_invoice_notifies_active_owners_only(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop_impower = _uid()
    prop = await make_property(test_engine, org=org, impower_id=prop_impower)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_now, c_past = _uid(), _uid()
    _, email_now, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_now
    )
    _, email_past, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_past
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=c_now)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_past, end_date=_PAST
    )

    invoice = {
        "state": "BOOKED",
        "propertyId": prop_impower,
        "amount": 1234.56,
        "counterpartContactName": "Baufirma GmbH",
        "name": "RE-2026-001",
    }
    client = _FakeImpowerClient(invoice)
    redis: Any = _FakeRedis()
    recorder = _RecordingEmail()

    async with sm() as s:
        sent = await notify_booked_invoice(
            s, client=client, invoice_id=4242, email_client=recorder, redis=redis
        )

    assert sent is True
    assert email_now in recorder.sent
    assert email_past not in recorder.sent  # former owner excluded

    # Dedupe: a second BOOKED redelivery does nothing.
    recorder2 = _RecordingEmail()
    async with sm() as s:
        sent2 = await notify_booked_invoice(
            s, client=client, invoice_id=4242, email_client=recorder2, redis=redis
        )
    assert sent2 is False
    assert recorder2.sent == []


async def test_non_booked_invoice_is_ignored(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop_impower = _uid()
    prop = await make_property(test_engine, org=org, impower_id=prop_impower)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c = _uid()
    await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c)
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=c)

    invoice = {"state": "READY", "propertyId": prop_impower, "amount": 99.0}
    client = _FakeImpowerClient(invoice)
    redis: Any = _FakeRedis()
    recorder = _RecordingEmail()

    async with sm() as s:
        sent = await notify_booked_invoice(
            s, client=client, invoice_id=7, email_client=recorder, redis=redis
        )
    assert sent is False
    assert recorder.sent == []
