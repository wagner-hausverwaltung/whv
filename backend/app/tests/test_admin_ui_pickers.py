"""Tests for the invite-form property + contact pickers (HTMX fragments)
mounted at /admin-ui/properties/search and
/admin-ui/properties/{uuid}/contacts/search.
"""

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.dependencies import ADMIN_COOKIE_NAME
from app.main import app
from app.models import User, UserRole
from app.tests._factories import make_property, make_user


def _login(client: TestClient, email: str, password: str) -> None:
    r = client.post(
        "/admin-ui/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert ADMIN_COOKIE_NAME in client.cookies


@pytest_asyncio.fixture
async def verwalter_session(test_engine: AsyncEngine) -> AsyncIterator[tuple[TestClient, User]]:
    """A logged-in Verwalter + their org, ready to hit pickers."""
    user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    with TestClient(app) as client:
        _login(client, email, password)
        yield client, user


# --- Property search ---------------------------------------------------------


def test_properties_search_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/admin-ui/properties/search?q=foo", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin-ui/login"


async def test_properties_search_below_min_chars_returns_hint(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, _ = verwalter_session
    r = client.get("/admin-ui/properties/search?q=a")
    assert r.status_code == 200
    assert "Mindestens 2 Zeichen" in r.text


async def test_properties_search_matches_by_name(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, user = verwalter_session
    # Build a property with a unique-ish substring we can grep for
    unique_token = f"PickerTest{uuid.uuid4().hex[:6]}"
    from app.tests._factories import make_org

    org = await make_org(test_engine)  # fresh org, not user's
    _other = await make_property(test_engine, org=org, name=f"OtherOrg {unique_token}")
    # And one in the user's org that should match
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import Property as PropertyModel
    from app.models import PropertyState, PropertyType

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PropertyModel(
                organization_id=user.organization_id,
                name=f"InScope {unique_token} Apartments",
                type=PropertyType.STRATA,
                state=PropertyState.READY,
                city="Stuttgart",
            )
        )
        await s.commit()

    r = client.get(f"/admin-ui/properties/search?q={unique_token}")
    assert r.status_code == 200
    # Match: our org's property is present
    assert f"InScope {unique_token}" in r.text
    # Org-scope: the other org's property with the same token is NOT present
    assert "OtherOrg" not in r.text


async def test_properties_search_matches_by_city(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, user = verwalter_session
    unique_city = f"PickerCity{uuid.uuid4().hex[:6]}"
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import Property as PropertyModel
    from app.models import PropertyState, PropertyType

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            PropertyModel(
                organization_id=user.organization_id,
                name="Some unrelated name",
                type=PropertyType.STRATA,
                state=PropertyState.READY,
                city=unique_city,
            )
        )
        await s.commit()

    r = client.get(f"/admin-ui/properties/search?q={unique_city}")
    assert r.status_code == 200
    assert "Some unrelated name" in r.text
    assert unique_city in r.text


# --- Contact search (property-scoped) ----------------------------------------


def test_contact_search_requires_auth() -> None:
    fake_uuid = uuid.uuid4()
    with TestClient(app) as client:
        r = client.get(
            f"/admin-ui/properties/{fake_uuid}/contacts/search?q=foo",
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin-ui/login"


async def test_contact_search_returns_empty_for_other_org_property(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, _ = verwalter_session
    from app.tests._factories import make_org

    other_org = await make_org(test_engine)
    other_prop = await make_property(test_engine, org=other_org)

    r = client.get(f"/admin-ui/properties/{other_prop.id}/contacts/search?q=")
    assert r.status_code == 200
    # No results shown — endpoint silently returns empty rather than 404
    # (avoids leaking cross-org property existence)
    assert "picker-results" not in r.text


async def test_contact_search_returns_contacts_linked_to_property(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, user = verwalter_session
    # Build the full chain — property + contact + contract + junction — under
    # the Verwalter's org directly (no factory helper exists for this exact shape).
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import (
        Contact as ContactModel,
    )
    from app.models import (
        ContactKind,
        ContractType,
        PropertyState,
        PropertyType,
    )
    from app.models import (
        Contract as ContractModel,
    )
    from app.models import (
        ContractContact as JunctionModel,
    )
    from app.models import (
        Property as PropertyModel,
    )

    unique_name = f"PickerLastname{uuid.uuid4().hex[:6]}"
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        prop = PropertyModel(
            organization_id=user.organization_id,
            name="Picker-Test-Objekt",
            type=PropertyType.STRATA,
            state=PropertyState.READY,
            city="Stuttgart",
        )
        s.add(prop)
        await s.flush()

        c_in_scope = ContactModel(
            organization_id=user.organization_id,
            impower_id=987654,
            kind=ContactKind.PERSON,
            first_name="Maria",
            last_name=unique_name,
        )
        s.add(c_in_scope)
        await s.flush()

        contract = ContractModel(
            organization_id=user.organization_id,
            property_id=prop.id,
            type=ContractType.OWNER,
        )
        s.add(contract)
        await s.flush()
        s.add(JunctionModel(contract_id=contract.id, contact_id=c_in_scope.id))

        # And a contact NOT linked to this property — should be excluded
        c_out_of_scope = ContactModel(
            organization_id=user.organization_id,
            impower_id=111222,
            kind=ContactKind.PERSON,
            first_name="Unrelated",
            last_name=f"OutOfScope{uuid.uuid4().hex[:6]}",
        )
        s.add(c_out_of_scope)
        await s.commit()
        property_id = prop.id

    # Search empty -> returns all contacts on the property
    r = client.get(f"/admin-ui/properties/{property_id}/contacts/search?q=")
    assert r.status_code == 200
    assert unique_name in r.text
    assert "OutOfScope" not in r.text
    # Result item carries the Impower contact ID as data-id (this is what
    # the inline JS shoves into the hidden contact_id_impower input)
    assert 'data-id="987654"' in r.text


async def test_contact_search_filters_by_query(
    test_engine: AsyncEngine, verwalter_session: tuple[TestClient, User]
) -> None:
    client, user = verwalter_session
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import Contact as ContactModel
    from app.models import (
        ContactKind,
        ContractType,
        PropertyState,
        PropertyType,
    )
    from app.models import Contract as ContractModel
    from app.models import ContractContact as JunctionModel
    from app.models import Property as PropertyModel

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        prop = PropertyModel(
            organization_id=user.organization_id,
            name="Q-Filter-Test",
            type=PropertyType.STRATA,
            state=PropertyState.READY,
            city="Stuttgart",
        )
        s.add(prop)
        await s.flush()

        matched = ContactModel(
            organization_id=user.organization_id,
            impower_id=555111,
            kind=ContactKind.PERSON,
            first_name="Alfonso",
            last_name="QFilterMatch",
        )
        unmatched = ContactModel(
            organization_id=user.organization_id,
            impower_id=555222,
            kind=ContactKind.PERSON,
            first_name="Beatrice",
            last_name="QFilterMiss",
        )
        s.add_all([matched, unmatched])
        await s.flush()

        for c in (matched, unmatched):
            contract = ContractModel(
                organization_id=user.organization_id,
                property_id=prop.id,
                type=ContractType.OWNER,
            )
            s.add(contract)
            await s.flush()
            s.add(JunctionModel(contract_id=contract.id, contact_id=c.id))

        await s.commit()
        property_id = prop.id

    r = client.get(f"/admin-ui/properties/{property_id}/contacts/search?q=Match")
    assert r.status_code == 200
    assert "QFilterMatch" in r.text
    assert "QFilterMiss" not in r.text


# --- Invite create still works with new form field source --------------------


async def test_invite_create_still_works_with_picker_set_id(
    test_engine: AsyncEngine,
) -> None:
    """Sanity: the form field name didn't change, so the existing invite
    handler still consumes `contact_id_impower` correctly."""
    # We need our own stub email client here — copy the pattern from test_admin_ui.py
    from app.integrations.email.client import EmailError, get_email_client

    class _StubEmailClient:
        def __init__(self) -> None:
            self.sent: list[dict[str, str]] = []

        async def send(self, *, to: str, subject: str, html: str, text: str) -> str:
            msg_id = f"sim-{uuid.uuid4()}"
            self.sent.append({"to": to, "subject": subject, "id": msg_id})
            return msg_id

        async def fail(self) -> None:
            raise EmailError("never")

    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    try:
        _user, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
        with TestClient(app) as client:
            _login(client, email, password)
            new_email = f"picker-end2end-{uuid.uuid4().hex[:8]}@test.de"
            r = client.post(
                "/admin-ui/invites/new",
                data={
                    "email": new_email,
                    "role": "eigentuemer",
                    "contact_id_impower": "1234567",  # as if the picker filled it
                    "ttl_days": "14",
                },
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert len(stub.sent) == 1
    finally:
        app.dependency_overrides.pop(get_email_client, None)
