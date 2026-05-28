"""Tests for the new-document notification: scope-aware recipient
resolution + the idempotent notify pass.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Document, DocumentKind, NotificationCategory, UserRole
from app.services import notification_prefs
from app.services.document_notify import (
    notify_new_documents,
    resolve_document_recipients,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_unit,
    make_user,
)


class _RecordingEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append(to)
        return "rec-id"


def _uid() -> int:
    import uuid

    return uuid.uuid4().int % 9_000_000_000_000_000


async def test_resolve_property_wide_reaches_all_owners_not_verwalter(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    other_prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner, c_other = _uid(), _uid()
    owner, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)  # must NOT be picked up
    other_owner, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_other
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=other_prop, contact_impower_id=c_other
    )

    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG)
    async with sm() as s:
        fresh = await s.get(Document, doc.id)
        assert fresh is not None
        recipients = await resolve_document_recipients(s, document=fresh)

    ids = {u.id for u in recipients}
    assert owner.id in ids
    assert other_owner.id not in ids  # different property
    # No Verwalter in the set.
    assert all(u.role != UserRole.VERWALTER for u in recipients)


async def test_resolve_unit_scoped_reaches_only_that_units_party(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    unit1 = await make_unit(test_engine, org=org, prop=prop)
    unit2 = await make_unit(test_engine, org=org, prop=prop)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c1, c2 = _uid(), _uid()
    owner1, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c1
    )
    owner2, _, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c2
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c1, unit=unit1
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c2, unit=unit2
    )

    doc = await make_document(
        test_engine, org=org, prop=prop, kind=DocumentKind.JAHRESABRECHNUNG, unit=unit1
    )
    async with sm() as s:
        fresh = await s.get(Document, doc.id)
        assert fresh is not None
        recipients = await resolve_document_recipients(s, document=fresh)

    ids = {u.id for u in recipients}
    assert owner1.id in ids
    assert owner2.id not in ids


async def test_notify_stamps_notified_at_and_is_idempotent(test_engine: AsyncEngine) -> None:
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
    doc = await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.WIRTSCHAFTSPLAN)

    recorder = _RecordingEmail()
    async with sm() as s:
        n1 = await notify_new_documents(s, email_client=recorder)
    # >= 1 (the shared test DB may hold eligible docs from sibling
    # tests — the pass is global by design); our owner must be among
    # those emailed.
    assert n1 >= 1
    assert owner_email in recorder.sent

    # notified_at is stamped → a second pass finds nothing new.
    async with sm() as s:
        stamped = await s.get(Document, doc.id)
        assert stamped is not None and stamped.notified_at is not None
    recorder2 = _RecordingEmail()
    async with sm() as s:
        n2 = await notify_new_documents(s, email_client=recorder2)
    assert n2 == 0
    assert recorder2.sent == []


async def test_notify_respects_document_email_opt_out(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_owner = _uid()
    owner, owner_email, _ = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=c_owner
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_owner
    )
    await make_document(test_engine, org=org, prop=prop, kind=DocumentKind.PROTOKOLL)

    async with sm() as s:
        await notification_prefs.set_settings(
            s,
            user_id=owner.id,
            settings={NotificationCategory.DOCUMENT: (True, False)},  # email OFF
        )
        await s.commit()

    recorder = _RecordingEmail()
    async with sm() as s:
        notified = await notify_new_documents(s, email_client=recorder)
    # Doc still processed (notified=1, push would fire) but no email sent.
    assert notified == 1
    assert owner_email not in recorder.sent
