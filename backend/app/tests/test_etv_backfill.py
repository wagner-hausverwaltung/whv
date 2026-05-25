"""Tests for `backfill_assemblies_from_invitations`.

Mirrors the staging scenario: a property has multiple
OWNERS_MEETING_INVITATION documents (one personalized PDF per
Eigentümer) clustered around a few distinct issued_dates. Each
distinct (property, date) becomes exactly one EtvAssembly stub.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import (
    AssemblyStatus,
    Document,
    DocumentKind,
    DocumentVisibility,
    EtvAssembly,
)
from app.services.etv import backfill_assemblies_from_invitations
from app.tests._factories import make_org, make_property


async def _make_invitation_doc(
    sm: async_sessionmaker[AsyncSession],
    *,
    org_id: uuid.UUID,
    property_id: uuid.UUID,
    issued: date,
) -> None:
    async with sm() as s:
        d = Document(
            organization_id=org_id,
            property_id=property_id,
            name="Einladung zur ordentlichen Eigentümerversammlung",
            kind=DocumentKind.SONSTIGES,
            impower_source_type="OWNERS_MEETING_INVITATION",
            visibility=DocumentVisibility.PRIVATE,
            issued_date=issued,
        )
        s.add(d)
        await s.commit()


async def test_backfill_one_assembly_per_invitation_date(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    # 3 personalized PDFs on 2024-08-01, 2 on 2024-11-15 → two
    # distinct meetings, expect 2 assemblies after backfill.
    for _ in range(3):
        await _make_invitation_doc(sm, org_id=org.id, property_id=prop.id, issued=date(2024, 8, 1))
    for _ in range(2):
        await _make_invitation_doc(
            sm, org_id=org.id, property_id=prop.id, issued=date(2024, 11, 15)
        )

    async with sm() as s:
        created, skipped, _ = await backfill_assemblies_from_invitations(
            s, organization_id=org.id, today=date(2026, 5, 25)
        )
        await s.commit()

    assert created == 2
    assert skipped == 0

    async with sm() as s:
        rows = (
            (
                await s.execute(
                    select(EtvAssembly)
                    .where(EtvAssembly.property_id == prop.id)
                    .order_by(EtvAssembly.scheduled_start)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    # Both are old enough that the heuristic stamps ABGEHALTEN.
    assert {r.status for r in rows} == {AssemblyStatus.ABGEHALTEN}
    # Title carries the meeting year for cheap UI sorting.
    assert rows[0].title == "Eigentümerversammlung 2024"
    assert rows[1].title == "Eigentümerversammlung 2024"
    # Date placeholder lines up with the invitation's issued_date
    # (converted to UTC from 18:00 Europe/Berlin).
    assert rows[0].scheduled_start.date() == date(2024, 8, 1)
    assert rows[1].scheduled_start.date() == date(2024, 11, 15)
    # Sanity: end is start + 3h.
    assert rows[0].scheduled_end - rows[0].scheduled_start == timedelta(hours=3)


async def test_backfill_is_idempotent(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    await _make_invitation_doc(sm, org_id=org.id, property_id=prop.id, issued=date(2024, 8, 1))

    async with sm() as s:
        c1, s1, _ = await backfill_assemblies_from_invitations(
            s, organization_id=org.id, today=date(2026, 5, 25)
        )
        await s.commit()
    assert (c1, s1) == (1, 0)

    async with sm() as s:
        c2, s2, _ = await backfill_assemblies_from_invitations(
            s, organization_id=org.id, today=date(2026, 5, 25)
        )
        await s.commit()
    assert (c2, s2) == (0, 1)


async def test_backfill_respects_existing_within_one_day(
    test_engine: AsyncEngine,
) -> None:
    """A Verwalter who pre-populates the actual meeting date (≈
    invitation_date + 3 weeks) shouldn't get a duplicate stub from
    the backfill. We fuzz ±1 day so an exact match isn't required."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    # Verwalter already created the assembly one day before the
    # invitation's issued_date.
    async with sm() as s:
        existing = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="Eigentümerversammlung",
            description="...",
            location="Vereinsheim",
            scheduled_start=datetime(2024, 7, 31, 18, 0, tzinfo=UTC),
            scheduled_end=datetime(2024, 7, 31, 21, 0, tzinfo=UTC),
            status=AssemblyStatus.ABGEHALTEN,
        )
        s.add(existing)
        await s.commit()

    await _make_invitation_doc(sm, org_id=org.id, property_id=prop.id, issued=date(2024, 8, 1))

    async with sm() as s:
        created, skipped, _ = await backfill_assemblies_from_invitations(
            s, organization_id=org.id, today=date(2026, 5, 25)
        )
        await s.commit()
    assert created == 0
    assert skipped == 1


async def test_backfill_status_heuristic(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    today = date(2026, 5, 25)
    # Older than 60d → ABGEHALTEN; recent → EINGELADEN.
    await _make_invitation_doc(
        sm,
        org_id=org.id,
        property_id=prop.id,
        issued=today - timedelta(days=100),
    )
    await _make_invitation_doc(
        sm,
        org_id=org.id,
        property_id=prop.id,
        issued=today - timedelta(days=10),
    )

    async with sm() as s:
        await backfill_assemblies_from_invitations(s, organization_id=org.id, today=today)
        await s.commit()

    async with sm() as s:
        rows = (
            (
                await s.execute(
                    select(EtvAssembly)
                    .where(EtvAssembly.property_id == prop.id)
                    .order_by(EtvAssembly.scheduled_start)
                )
            )
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == [
        AssemblyStatus.ABGEHALTEN,
        AssemblyStatus.EINGELADEN,
    ]
