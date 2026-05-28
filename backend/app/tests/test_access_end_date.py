"""Former-owner access cutoff: a contract with a past end_date must
stop granting property/document visibility AND stop pulling the person
into notification fan-outs. A current contract (no end_date, or a
future one) keeps full access.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import AssemblyStatus, Document, DocumentKind, EtvAssembly, UserRole
from app.services.document_notify import resolve_document_recipients
from app.services.etv import resolve_assembly_invitation_recipients
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_user,
)


def _uid() -> int:
    return uuid.uuid4().int % 9_000_000_000_000_000


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


async def _make_assembly(
    sm: async_sessionmaker[Any], *, org_id: uuid.UUID, property_id: uuid.UUID
) -> uuid.UUID:
    async with sm() as s:
        a = EtvAssembly(
            organization_id=org_id,
            property_id=property_id,
            title="Eigentümerversammlung 2026",
            description="",
            location="(noch nicht erfasst)",
            status=AssemblyStatus.EINGELADEN,
            scheduled_start=datetime.now(UTC),
            scheduled_end=datetime.now(UTC) + timedelta(hours=3),
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
    return a.id


_PAST = date(2020, 1, 1)


async def test_former_owner_loses_property_visibility(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)

    c_now, c_past = _uid(), _uid()
    _, email_now, pw_now = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_now
    )
    _, email_past, pw_past = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_past
    )
    # Active contract (no end_date) vs. ended contract (sold in 2020).
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=c_now)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_past, end_date=_PAST
    )

    headers_now = {"Authorization": f"Bearer {_login(email_now, pw_now)}"}
    headers_past = {"Authorization": f"Bearer {_login(email_past, pw_past)}"}
    with TestClient(app) as client:
        now_ids = {p["id"] for p in client.get("/me/properties", headers=headers_now).json()}
        past_ids = {p["id"] for p in client.get("/me/properties", headers=headers_past).json()}

    assert str(prop.id) in now_ids
    assert str(prop.id) not in past_ids


async def test_future_end_date_still_visible(test_engine: AsyncEngine) -> None:
    """A contract that ends in the future is still active today."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    c = _uid()
    _, email, pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c
    )
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=c,
        end_date=date.today() + timedelta(days=365),
    )
    headers = {"Authorization": f"Bearer {_login(email, pw)}"}
    with TestClient(app) as client:
        ids = {p["id"] for p in client.get("/me/properties", headers=headers).json()}
    assert str(prop.id) in ids


async def test_former_owner_excluded_from_etv_invitation_recipients(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_now, c_past = _uid(), _uid()
    owner_now, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_now
    )
    owner_past, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_past
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=c_now)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_past, end_date=_PAST
    )

    aid = await _make_assembly(sm, org_id=org.id, property_id=prop.id)
    async with sm() as s:
        assembly = await s.get(EtvAssembly, aid)
        assert assembly is not None
        recipients = await resolve_assembly_invitation_recipients(s, assembly=assembly)

    ids = {u.id for u in recipients}
    assert owner_now.id in ids
    assert owner_past.id not in ids


async def test_former_owner_excluded_from_document_recipients(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_now, c_past = _uid(), _uid()
    owner_now, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_now
    )
    owner_past, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_past
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=c_now)
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_past, end_date=_PAST
    )
    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG)

    async with sm() as s:
        fresh = await s.get(Document, doc.id)
        assert fresh is not None
        recipients = await resolve_document_recipients(s, document=fresh)

    ids = {u.id for u in recipients}
    assert owner_now.id in ids
    assert owner_past.id not in ids
