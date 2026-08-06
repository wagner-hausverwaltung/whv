"""Tests for the unified /me/activity feed.

Mirrors the style of test_me.py (TestClient + JWT login + _factories
helpers). Supporting domain rows (resolutions, ETV assemblies, meters,
announcements) are created directly through async_sessionmaker(test_engine)
the same way the other domain tests do.

The ACL test is the load-bearing one: it proves a user does NOT see
items belonging to a property/owner they have no access to.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import (
    Announcement,
    CircularResolution,
    ContractType,
    Meter,
    MeterType,
    Organization,
    Property,
    ResolutionMode,
    ResolutionStatus,
    User,
    UserRole,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


def _activity(token: str, limit: int | None = None) -> list[dict[str, Any]]:
    url = "/me/activity" if limit is None else f"/me/activity?limit={limit}"
    with TestClient(app) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    body: list[dict[str, Any]] = response.json()
    return body


async def _add_open_resolution(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    title: str,
    closes_in_days: int = 5,
) -> CircularResolution:
    now = datetime.now(UTC)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        r = CircularResolution(
            organization_id=org.id,
            property_id=prop.id,
            title=title,
            description="Beschlusstext",
            mode=ResolutionMode.MEHRHEITS,
            status=ResolutionStatus.OFFEN,
            opens_at=now - timedelta(days=1),
            closes_at=now + timedelta(days=closes_in_days),
            required_quorum=1,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
    return r


async def _add_meter_due(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    due: date,
    description: str = "Allgemeinstrom",
) -> Meter:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        m = Meter(
            organization_id=org.id,
            property_id=prop.id,
            meter_number=f"Z-{description}",
            meter_type=MeterType.STROM,
            description=description,
            reading_due_date=due,
        )
        s.add(m)
        await s.commit()
        await s.refresh(m)
    return m


async def _add_published_announcement(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    author: User,
    title: str,
) -> Announcement:
    now = datetime.now(UTC)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        a = Announcement(
            organization_id=org.id,
            property_id=prop.id,
            created_by_user_id=author.id,
            title=title,
            body="Mitteilungstext",
            audience_eigentuemer=True,
            audience_mieter=True,
            audience_beirat=True,
            scheduled_publish_at=now - timedelta(minutes=20),
            notification_sent_at=now - timedelta(minutes=10),
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
    return a


# --- auth -------------------------------------------------------------------


async def test_activity_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get("/me/activity")
    assert response.status_code == 401


# --- empty feed -------------------------------------------------------------


async def test_activity_empty_for_user_with_no_properties(test_engine: AsyncEngine) -> None:
    # Eigentümer with no contact link → no visible properties → empty feed.
    _, email, password = await make_user(
        test_engine, role=UserRole.EIGENTUEMER, contact_id_impower=None
    )
    token = _login(email, password)
    assert _activity(token) == []


async def test_activity_empty_when_nothing_to_show(test_engine: AsyncEngine) -> None:
    # Verwalter sees the property but there are no events on it.
    org = await make_org(test_engine)
    await make_property(test_engine, org=org)
    _, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)
    assert _activity(token) == []


# --- items show up ----------------------------------------------------------


async def test_open_resolution_shows_up_for_owner(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    impower_contact = 9_100_001
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    res = await _add_open_resolution(test_engine, org=org, prop=prop, title="Dachsanierung")

    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    feed = _activity(token)
    res_items = [i for i in feed if i["type"] == "RESOLUTION"]
    assert len(res_items) == 1
    item = res_items[0]
    assert item["id"] == str(res.id)
    assert item["title"] == "Dachsanierung"
    assert item["property_id"] == str(prop.id)
    assert item["deep_link"] == f"whv://resolution/{res.id}"
    # Deadline-driven → top priority.
    assert item["priority"] == 0


async def test_resolution_hidden_from_mieter(test_engine: AsyncEngine) -> None:
    """Beschlüsse are OWNER-only — a Mieter on the same property must NOT
    see them even though the property is visible to them."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    # Mieter contract on the property (visible) but NOT an OWNER contract.
    impower_contact = 9_100_010
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=impower_contact,
        contract_type=ContractType.TENANT,
    )
    await _add_open_resolution(test_engine, org=org, prop=prop, title="Nur für Eigentümer")

    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.MIETER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    feed = _activity(token)
    assert [i for i in feed if i["type"] == "RESOLUTION"] == []


async def test_meter_due_and_announcement_show_up(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    impower_contact = 9_100_020
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    verwalter, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    meter = await _add_meter_due(
        test_engine, org=org, prop=prop, due=date.today() + timedelta(days=10)
    )
    ann = await _add_published_announcement(
        test_engine, org=org, prop=prop, author=verwalter, title="Treppenhausreinigung"
    )

    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    feed = _activity(token)
    by_type = {i["type"]: i for i in feed}

    assert "METER_DUE" in by_type
    assert by_type["METER_DUE"]["id"] == str(meter.id)
    assert by_type["METER_DUE"]["deep_link"] == f"whv://meter/{meter.id}"
    assert by_type["METER_DUE"]["priority"] == 0

    assert "ANNOUNCEMENT" in by_type
    assert by_type["ANNOUNCEMENT"]["id"] == str(ann.id)
    assert by_type["ANNOUNCEMENT"]["deep_link"] == f"whv://announcement/{ann.id}"

    # Ranking: METER_DUE (priority 0) sorts before ANNOUNCEMENT (priority 4).
    types_in_order = [i["type"] for i in feed]
    assert types_in_order.index("METER_DUE") < types_in_order.index("ANNOUNCEMENT")


async def test_meter_due_cleared_after_reading(test_engine: AsyncEngine) -> None:
    """A reading on/after the due date implicitly clears the reminder."""
    from decimal import Decimal

    from app.models import MeterReading

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    impower_contact = 9_100_030
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    due = date.today() + timedelta(days=5)
    meter = await _add_meter_due(test_engine, org=org, prop=prop, due=due)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(MeterReading(meter_id=meter.id, value=Decimal("123.0"), read_on=due))
        await s.commit()

    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    feed = _activity(token)
    assert [i for i in feed if i["type"] == "METER_DUE"] == []


# --- ACL: cross-property / cross-owner isolation ----------------------------


async def test_activity_does_not_leak_other_property_items(test_engine: AsyncEngine) -> None:
    """The crucial ACL test.

    Two owners, two properties in the same org. Owner A holds a contract
    only on property A; owner B only on property B. Each property carries
    an open resolution + a due meter. Owner A's feed must contain ONLY
    property A's items and never property B's — proving the feed never
    crosses the property/owner boundary.
    """
    org = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org, name="Haus A")
    prop_b = await make_property(test_engine, org=org, name="Haus B")

    contact_a = 9_100_100
    contact_b = 9_100_101
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop_a, contact_impower_id=contact_a
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop_b, contact_impower_id=contact_b
    )

    res_a = await _add_open_resolution(test_engine, org=org, prop=prop_a, title="A-Beschluss")
    res_b = await _add_open_resolution(test_engine, org=org, prop=prop_b, title="B-Beschluss")
    meter_a = await _add_meter_due(
        test_engine,
        org=org,
        prop=prop_a,
        due=date.today() + timedelta(days=7),
        description="A-Strom",
    )
    meter_b = await _add_meter_due(
        test_engine,
        org=org,
        prop=prop_b,
        due=date.today() + timedelta(days=7),
        description="B-Strom",
    )

    _, email_a, password_a = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=contact_a
    )
    token_a = _login(email_a, password_a)
    feed = _activity(token_a)

    ids = {i["id"] for i in feed}
    pids = {i["property_id"] for i in feed}

    # Owner A sees A's items.
    assert str(res_a.id) in ids
    assert str(meter_a.id) in ids
    # Owner A NEVER sees B's items.
    assert str(res_b.id) not in ids
    assert str(meter_b.id) not in ids
    assert str(prop_b.id) not in pids
    # Every surfaced item belongs to property A.
    assert pids == {str(prop_a.id)}


async def test_activity_respects_limit(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    impower_contact = 9_100_200
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    # Three open resolutions.
    for i in range(3):
        await _add_open_resolution(
            test_engine, org=org, prop=prop, title=f"Beschluss {i}", closes_in_days=i + 1
        )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    feed = _activity(token, limit=2)
    assert len(feed) == 2


async def test_reversed_invoice_is_not_announced_in_the_feed(test_engine: AsyncEngine) -> None:
    """Hiding a storno in the Dienstleister tab is not enough: the widget
    pushed the same invoice at owners, with a deep link whose detail now
    404s — a dead end pointing at a bill the WEG never owed."""
    import time as _time

    from app.models import Contact, ContactKind, Document, DocumentKind
    from app.services.reversed_invoices import get_reversed_invoice_cache
    from app.tests._factories import make_document

    property_impower_id = 9_400_777
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, impower_id=property_impower_id)
    impower_contact = 9_100_077
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        vendor = Contact(
            organization_id=org.id, kind=ContactKind.COMPANY, company_name="Keller GmbH"
        )
        s.add(vendor)
        await s.commit()
        await s.refresh(vendor)

    booked = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG, contact=vendor
    )
    storno = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.RECHNUNG, contact=vendor
    )
    now = datetime.now(UTC)
    async with sm() as s:
        for doc_id, source_id in ((booked.id, 5001), (storno.id, 5002)):
            row = await s.get(Document, doc_id)
            assert row is not None
            row.raw_jsonb = {"sourceId": source_id}
            row.last_synced_at = now
        await s.commit()

    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )

    cache = get_reversed_invoice_cache()
    async with cache._lock:
        cache._store[property_impower_id] = (_time.monotonic() + 600, {5002})
    try:
        token = _login(email, password)
        feed = _activity(token)
    finally:
        await cache.clear()

    invoice_ids = {i["id"] for i in feed if i["type"] == "INVOICE"}
    assert str(booked.id) in invoice_ids
    assert str(storno.id) not in invoice_ids
