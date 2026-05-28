"""Tests for the "new ETV invitation available" notification.

When `backfill_assemblies_from_invitations` turns a fresh
OWNERS_MEETING_INVITATION document into an assembly stub, the property's
Eigentümer + Beirat (and every Verwalter) get an email + push — parity
with the letter Impower already mailed. Two things must hold:

  - Recipient resolution mirrors portal property-visibility (owners +
    Beirat on the property, plus all Verwalter) and EXCLUDES Mieter /
    Dienstleister, who aren't invited to the Eigentümerversammlung.
  - The notify step is freshness-gated so a first-run historical
    backfill doesn't blast a push for every ETV in the archive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import AssemblyStatus, EtvAssembly, UserRole
from app.services.etv import (
    notify_owners_of_new_invitations,
    resolve_assembly_invitation_recipients,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)


def _uid() -> int:
    """Collision-proof impower_id (BigInteger, globally UNIQUE column)."""
    return uuid.uuid4().int % 9_000_000_000_000_000


class _RecordingEmail:
    """Stand-in for EmailClient that records `send` calls instead of
    hitting Resend. Matches the keyword-only `send` signature the
    notify helper uses."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append((to, subject))
        return "recorded-message-id"


async def _make_assembly(
    sm: async_sessionmaker[Any],
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    status: AssemblyStatus,
    start: datetime,
) -> uuid.UUID:
    async with sm() as s:
        a = EtvAssembly(
            organization_id=org_id,
            property_id=property_id,
            title="Eigentümerversammlung 2026",
            description="",
            location="(noch nicht erfasst)",
            status=status,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=3),
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
    return a.id


async def test_resolve_recipients_owners_beirat_verwalter_not_mieter(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner, c_beirat, c_mieter = _uid(), _uid(), _uid()
    verwalter, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    owner, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    beirat, _, _ = await make_user(
        test_engine, org=org, role=UserRole.BEIRAT, contact_id_impower=c_beirat
    )
    mieter, _, _ = await make_user(
        test_engine, org=org, role=UserRole.MIETER, contact_id_impower=c_mieter
    )
    for cid in (c_owner, c_beirat, c_mieter):
        await make_contact_with_contract_link(
            test_engine, org=org, prop=prop, contact_impower_id=cid
        )

    aid = await _make_assembly(
        sm,
        org_id=org.id,
        property_id=prop.id,
        status=AssemblyStatus.EINGELADEN,
        start=datetime.now(UTC),
    )
    async with sm() as s:
        assembly = await s.get(EtvAssembly, aid)
        assert assembly is not None
        recipients = await resolve_assembly_invitation_recipients(s, assembly=assembly)

    ids = {u.id for u in recipients}
    assert verwalter.id in ids
    assert owner.id in ids
    assert beirat.id in ids
    assert mieter.id not in ids


async def test_resolve_recipients_scoped_to_the_assemblys_property(
    test_engine: AsyncEngine,
) -> None:
    """An owner of a *different* property in the same org must NOT be
    notified about this assembly."""
    org = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org)
    prop_b = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_a, c_b = _uid(), _uid()
    owner_a, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_a
    )
    owner_b, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_b
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop_a, contact_impower_id=c_a)
    await make_contact_with_contract_link(test_engine, org=org, prop=prop_b, contact_impower_id=c_b)

    aid = await _make_assembly(
        sm,
        org_id=org.id,
        property_id=prop_a.id,
        status=AssemblyStatus.EINGELADEN,
        start=datetime.now(UTC),
    )
    async with sm() as s:
        assembly = await s.get(EtvAssembly, aid)
        assert assembly is not None
        recipients = await resolve_assembly_invitation_recipients(s, assembly=assembly)

    ids = {u.id for u in recipients}
    assert owner_a.id in ids
    assert owner_b.id not in ids


async def test_notify_fires_for_fresh_invitation(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner = _uid()
    _, owner_email, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )

    aid = await _make_assembly(
        sm,
        org_id=org.id,
        property_id=prop.id,
        status=AssemblyStatus.EINGELADEN,
        start=datetime.now(UTC),
    )
    recorder = _RecordingEmail()
    async with sm() as s:
        notified = await notify_owners_of_new_invitations(
            s, assembly_ids=[aid], email_client=recorder
        )

    assert notified == 1
    assert owner_email in {to for to, _ in recorder.sent}


async def test_notify_skips_historical_backfill(test_engine: AsyncEngine) -> None:
    """A stub whose scheduled_start (= the invitation's issued_date) is
    well outside the freshness window must not notify — this is the
    guard that stops the first production backfill from spamming owners
    about ETVs from years ago."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner = _uid()
    await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )

    old_aid = await _make_assembly(
        sm,
        org_id=org.id,
        property_id=prop.id,
        status=AssemblyStatus.ABGEHALTEN,
        start=datetime.now(UTC) - timedelta(days=400),
    )
    recorder = _RecordingEmail()
    async with sm() as s:
        notified = await notify_owners_of_new_invitations(
            s, assembly_ids=[old_aid], email_client=recorder
        )

    assert notified == 0
    assert recorder.sent == []


async def test_notify_empty_ids_is_noop(test_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    recorder = _RecordingEmail()
    async with sm() as s:
        notified = await notify_owners_of_new_invitations(s, assembly_ids=[], email_client=recorder)
    assert notified == 0
    assert recorder.sent == []
