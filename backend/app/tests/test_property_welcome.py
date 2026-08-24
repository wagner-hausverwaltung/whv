"""Automatic welcome announcement for newly taken-over objects.

Covers what the feature must guarantee: exactly one message per new WEG/MV,
never for objects that existed before (they are backfilled), never twice,
the right audience per type, and the text a Verwalter would actually send.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import (
    Announcement,
    Organization,
    Property,
    PropertyState,
    PropertyType,
    UserRole,
)
from app.services.property_welcome import welcome_body, welcome_new_properties
from app.tests._factories import make_org, make_property, make_user


async def _fresh_property(
    engine: AsyncEngine,
    session: AsyncSession,
    *,
    org: Organization,
    name: str,
    type_: PropertyType,
    state: PropertyState = PropertyState.READY,
) -> Property:
    """A property as the sync leaves it for a brand-new object: no
    welcome_sent_at yet."""
    prop = await make_property(engine, org=org, name=name, type=type_)
    row = await session.get(Property, prop.id)
    assert row is not None
    row.state = state
    row.welcome_sent_at = None
    await session.commit()
    return row


async def _announcements_for(session: AsyncSession, property_id: uuid.UUID) -> list[Announcement]:
    return list(
        (
            await session.scalars(
                select(Announcement).where(Announcement.property_id == property_id)
            )
        ).all()
    )


async def test_welcomes_new_weg_once_with_owner_audience(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await _fresh_property(
        test_engine,
        session,
        org=org,
        name="WEG Burckhardtstraße 42, 70374 Stuttgart",
        type_=PropertyType.OWNER,
    )

    await welcome_new_properties(session, settings=get_settings())

    rows = await _announcements_for(session, prop.id)
    assert len(rows) == 1
    ann = rows[0]
    assert ann.property_id == prop.id
    assert "WEG Burckhardtstraße 42" in ann.title
    # WEG: owners + Beirat, no tenants
    assert ann.audience_eigentuemer is True
    assert ann.audience_beirat is True
    assert ann.audience_mieter is False
    # goes through the normal editorial delay, so it is reviewable
    assert ann.scheduled_publish_at is not None
    assert ann.notification_sent_at is None

    # the object is stamped → a second sync must not post again
    refreshed = await session.get(Property, prop.id)
    assert refreshed is not None and refreshed.welcome_sent_at is not None
    await welcome_new_properties(session, settings=get_settings())
    assert len(await _announcements_for(session, prop.id)) == 1


async def test_mv_audience_includes_tenants(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await _fresh_property(
        test_engine,
        session,
        org=org,
        name="MV Hauptstraße 103, 71642 Ludwigsburg",
        type_=PropertyType.RENTAL,
    )

    await welcome_new_properties(session, settings=get_settings())
    ann = (await _announcements_for(session, prop.id))[0]
    assert ann.audience_mieter is True
    assert ann.audience_eigentuemer is True
    assert ann.audience_beirat is False


@pytest.mark.parametrize(
    ("state", "type_"),
    [
        # not activated in Impower yet — the hand-over hasn't happened
        (PropertyState.DRAFT, PropertyType.OWNER),
        # SEV is a single owner's mandate and gets a personal hand-over
        (PropertyState.READY, PropertyType.STRATA),
    ],
)
async def test_skips_draft_and_sev(
    test_engine: AsyncEngine, session: AsyncSession, state: PropertyState, type_: PropertyType
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await _fresh_property(
        test_engine, session, org=org, name="Objekt", type_=type_, state=state
    )

    await welcome_new_properties(session, settings=get_settings())
    assert await _announcements_for(session, prop.id) == []


async def test_skips_already_welcomed_and_handed_over_objects(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """Objects that existed when the feature shipped carry a backfilled
    welcome_sent_at; a handed-back object (deleted_at) is out too."""
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    old = await _fresh_property(
        test_engine, session, org=org, name="WEG Alt", type_=PropertyType.OWNER
    )
    old.welcome_sent_at = datetime.now(UTC)
    gone = await _fresh_property(
        test_engine, session, org=org, name="WEG Abgegeben", type_=PropertyType.OWNER
    )
    gone.deleted_at = datetime.now(UTC)
    await session.commit()

    await welcome_new_properties(session, settings=get_settings())
    assert await _announcements_for(session, old.id) == []
    assert await _announcements_for(session, gone.id) == []


async def test_no_verwalter_skips_without_stamping(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """Without an author we cannot create the announcement — the object must
    stay unstamped so the next sync retries instead of losing the welcome."""
    org = await make_org(test_engine)
    prop = await _fresh_property(
        test_engine, session, org=org, name="WEG Ohne Verwalter", type_=PropertyType.OWNER
    )

    await welcome_new_properties(session, settings=get_settings())
    assert await _announcements_for(session, prop.id) == []
    refreshed = await session.get(Property, prop.id)
    assert refreshed is not None and refreshed.welcome_sent_at is None


def test_body_mentions_portal_app_and_contact_without_a_start_date() -> None:
    settings = get_settings()
    prop = Property(name="WEG Burckhardtstraße 42, 70374 Stuttgart", type=PropertyType.OWNER)

    body = welcome_body(prop, settings=settings)

    assert "ab sofort" in body
    assert "WEG Burckhardtstraße 42" in body
    assert settings.portal_base_url in body
    assert "ullrich@wagner-hausverwaltung.com" in body
    assert "+49 156 79 062409" in body
    # no invented hand-over date; the IBAN itself is never interpolated —
    # the text points at the comment where the Verwalter posts it per object
    assert "01.01." not in body
    assert re.search(r"\bDE\d{2}[\d ]{10,}", body) is None
    assert "im Kommentar zu dieser Mitteilung" in body
    assert "SEPA-Lastschriftmandat" in body
    # app store: search hint while the URL is unset
    assert "App Store" in body


def test_body_uses_app_store_url_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={"app_store_url": "https://apps.apple.com/de/app/id123456789"}
    )
    prop = Property(name="MV Hauptstraße 103", type=PropertyType.RENTAL)

    body = welcome_body(prop, settings=settings)
    assert "https://apps.apple.com/de/app/id123456789" in body


async def test_two_new_objects_each_get_their_own_message(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """The text is per object — no cross-contamination of names."""
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    a = await _fresh_property(
        test_engine, session, org=org, name="WEG Burckhardtstraße 42", type_=PropertyType.OWNER
    )
    b = await _fresh_property(
        test_engine, session, org=org, name="WEG Eibenweg 5/7", type_=PropertyType.OWNER
    )

    await welcome_new_properties(session, settings=get_settings())
    body_a = (await _announcements_for(session, a.id))[0].body
    body_b = (await _announcements_for(session, b.id))[0].body
    assert "Burckhardtstraße 42" in body_a and "Eibenweg" not in body_a
    assert "Eibenweg 5/7" in body_b and "Burckhardtstraße" not in body_b


async def test_other_orgs_verwalter_is_not_used_as_author(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    """The author must come from the property's own organization."""
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    verwalter_b, _e, _p = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    prop = await _fresh_property(
        test_engine, session, org=org_a, name="WEG Fremd", type_=PropertyType.OWNER
    )

    # org_a has no Verwalter → nothing created, and org_b's user is untouched
    await welcome_new_properties(session, settings=get_settings())
    assert await _announcements_for(session, prop.id) == []
    assert verwalter_b.organization_id == org_b.id


async def test_session_factory_isolation(test_engine: AsyncEngine) -> None:
    """Sanity: the helper commits per object, so a fresh session sees them."""
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    async with sm() as s1:
        prop = await _fresh_property(
            test_engine, s1, org=org, name="WEG Sichtbar", type_=PropertyType.OWNER
        )
        await welcome_new_properties(s1, settings=get_settings())
    async with sm() as s2:
        assert len(await _announcements_for(s2, prop.id)) == 1
