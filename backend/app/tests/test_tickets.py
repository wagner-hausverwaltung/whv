"""Tickets v1 — owner + admin flow, scope safety, internal-note hiding,
email notifications, status transitions.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.email.client import EmailError, get_email_client
from app.main import app
from app.models import (
    AuditLog,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketStatus,
    UserRole,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)


class _StubEmailClient:
    def __init__(self) -> None:
        # `headers` value is a nested dict, so widen to Any for typing.
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        to: str | list[str],
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        msg_id = f"sim-{uuid.uuid4()}"
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "html": html,
                "text": text,
                "headers": headers or {},
                "reply_to": reply_to,
                "attachments": attachments or [],
            }
        )
        return msg_id


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


def _login(email: str, password: str) -> str:
    """Returns a fresh access token. MUST be called outside any other
    `with TestClient(app)` block — each TestClient context runs the FastAPI
    lifespan, and the shutdown half closes the shared DB engine."""
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Owner create + read ------------------------------------------------------


async def test_owner_can_create_and_read_own_ticket(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    # Verwalter exists (so the new-ticket notification has a recipient — but
    # we seed it in a *different* org here so the no-recipients code path
    # also gets coverage)
    await make_user(test_engine, role=UserRole.VERWALTER)
    org_a = await make_org(test_engine)
    eigent, email, pw = await make_user(test_engine, org=org_a, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)

    with TestClient(app) as client:
        r = client.post(
            "/me/tickets",
            headers=_auth(token),
            json={
                "subject": "Wasserschaden im Keller",
                "body": "Seit gestern Abend tropft es vom Heizungsrohr.",
                "category": "SCHADEN_ALLGEMEIN",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["subject"] == "Wasserschaden im Keller"
    assert body["status"] == "NEU"
    assert body["category"] == "SCHADEN_ALLGEMEIN"
    assert body["created_by_user_id"] == str(eigent.id)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["body"].startswith("Seit gestern")
    assert body["messages"][0]["is_internal_note"] is False

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "ticket_created",
                AuditLog.target_id == body["id"],
            )
        )
        assert audit is not None


async def test_owner_sees_only_their_own_tickets(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    _eigent_a, email_a, pw_a = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _eigent_b, email_b, pw_b = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token_a = _login(email_a, pw_a)
    token_b = _login(email_b, pw_b)

    with TestClient(app) as client:
        client.post(
            "/me/tickets",
            headers=_auth(token_a),
            json={"subject": "A only", "body": "private body", "category": "SONSTIGES_OTHER"},
        )
        r = client.get("/me/tickets", headers=_auth(token_b))
    assert r.status_code == 200
    assert r.json() == []


async def test_owner_thread_excludes_internal_notes(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    verwalter, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    eigent, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    e_token = _login(e_email, e_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(e_token),
            json={"subject": "Frage", "body": "Initialer Text", "category": "WEG_ANFRAGE"},
        )
        ticket_id = create.json()["id"]

        client.post(
            f"/admin/tickets/{ticket_id}/messages",
            headers=_auth(vw_token),
            json={"body": "intern: bitte selbst recherchieren", "is_internal_note": True},
        )
        client.post(
            f"/admin/tickets/{ticket_id}/messages",
            headers=_auth(vw_token),
            json={
                "body": "Hallo, danke für Ihre Anfrage. Kümmern uns.",
                "is_internal_note": False,
            },
        )

        owner_detail = client.get(f"/me/tickets/{ticket_id}", headers=_auth(e_token))
        admin_detail = client.get(f"/admin/tickets/{ticket_id}", headers=_auth(vw_token))

    owner_bodies = [m["body"] for m in owner_detail.json()["messages"]]
    admin_bodies = [m["body"] for m in admin_detail.json()["messages"]]
    assert "intern: bitte selbst recherchieren" not in owner_bodies
    assert "intern: bitte selbst recherchieren" in admin_bodies
    assert "Hallo, danke für Ihre Anfrage. Kümmern uns." in owner_bodies
    assert "Hallo, danke für Ihre Anfrage. Kümmern uns." in admin_bodies
    assert verwalter.organization_id == eigent.organization_id


async def test_owner_cannot_post_internal_note_via_me_endpoint(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    eigent, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(token),
            json={"subject": "Test ticket", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        ticket_id = create.json()["id"]
        client.post(
            f"/me/tickets/{ticket_id}/messages",
            headers=_auth(token),
            json={"body": "Versuch interne Notiz", "is_internal_note": True},
        )

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.scalars(
                select(TicketMessage).where(TicketMessage.ticket_id == uuid.UUID(ticket_id))
            )
        ).all()
    assert all(m.is_internal_note is False for m in rows)
    assert any(m.author_user_id == eigent.id for m in rows)


async def test_verwalter_sees_all_tickets_in_org(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    _vw, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _ea, ea_email, ea_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _eb, eb_email, eb_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(ea_email, ea_pw)
    eb_token = _login(eb_email, eb_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        for tok, subj in [(ea_token, "A ticket"), (eb_token, "B ticket")]:
            r = client.post(
                "/me/tickets",
                headers=_auth(tok),
                json={"subject": subj, "body": "Body text", "category": "SONSTIGES_OTHER"},
            )
            assert r.status_code == 201, r.text
        r = client.get("/admin/tickets", headers=_auth(vw_token))

    subjects = {t["subject"] for t in r.json()}
    assert {"A ticket", "B ticket"} <= subjects


async def test_ticket_is_invisible_across_orgs(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    _, ea_email, ea_pw = await make_user(test_engine, org=org_a, role=UserRole.EIGENTUEMER)
    _vw_b, vw_b_email, vw_b_pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    ea_token = _login(ea_email, ea_pw)
    b_token = _login(vw_b_email, vw_b_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={"subject": "org A only", "body": "secret", "category": "SONSTIGES_OTHER"},
        )
        ticket_id = create.json()["id"]

        list_r = client.get("/admin/tickets", headers=_auth(b_token))
        assert all(t["id"] != ticket_id for t in list_r.json())

        get_r = client.get(f"/admin/tickets/{ticket_id}", headers=_auth(b_token))
    assert get_r.status_code == 404


async def test_email_sent_on_owner_create_but_not_on_internal_note(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    _vw, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _ea, ea_email, ea_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(ea_email, ea_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={
                "subject": "Heizung kalt",
                "body": "Bitte prüfen.",
                "category": "SCHADEN_ALLGEMEIN",
            },
        )
        ticket_id = create.json()["id"]
        assert len(stub_email.sent) == 1
        assert vw_email in stub_email.sent[0]["to"]
        assert "Heizung kalt" in stub_email.sent[0]["subject"]

        client.post(
            f"/admin/tickets/{ticket_id}/messages",
            headers=_auth(vw_token),
            json={"body": "Intern", "is_internal_note": True},
        )
        assert len(stub_email.sent) == 1

        client.post(
            f"/admin/tickets/{ticket_id}/messages",
            headers=_auth(vw_token),
            json={"body": "Wir kümmern uns.", "is_internal_note": False},
        )
        assert len(stub_email.sent) == 2
        assert ea_email in stub_email.sent[1]["to"]


async def test_create_succeeds_even_when_email_send_fails(
    test_engine: AsyncEngine,
) -> None:
    """Email is best-effort. A Resend outage must not block ticket creation."""
    failing = _StubEmailClient()

    async def _fail(
        *,
        to: str | list[str],
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        raise EmailError("simulated")

    failing.send = _fail  # type: ignore[method-assign]

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield failing

    app.dependency_overrides[get_email_client] = _override
    try:
        org = await make_org(test_engine)
        await make_user(test_engine, org=org, role=UserRole.VERWALTER)
        _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
        token = _login(e_email, e_pw)
        with TestClient(app) as client:
            r = client.post(
                "/me/tickets",
                headers=_auth(token),
                json={"subject": "Status-Test", "body": "Body text", "category": "SONSTIGES_OTHER"},
            )
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_email_client, None)


async def test_status_lifecycle_owner_close(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(e_email, e_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(token),
            json={"subject": "Status-Test", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        ticket_id = create.json()["id"]
        assert create.json()["status"] == "NEU"

        close = client.post(f"/me/tickets/{ticket_id}/close", headers=_auth(token))
        assert close.status_code == 200
        assert close.json()["status"] == "GESCHLOSSEN"
        assert close.json()["closed_at"] is not None

        bad = client.post(
            f"/me/tickets/{ticket_id}/messages",
            headers=_auth(token),
            json={"body": "trying", "is_internal_note": False},
        )
        assert bad.status_code == 400


async def test_admin_patch_status_writes_audit_row(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    _vw, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(e_email, e_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={"subject": "Status-Test", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        ticket_id = create.json()["id"]
        r = client.patch(
            f"/admin/tickets/{ticket_id}",
            headers=_auth(vw_token),
            json={"status": "OFFEN"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "OFFEN"

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "ticket_status_changed",
                AuditLog.target_id == ticket_id,
            )
        )
        assert audit is not None
        assert audit.payload_json is not None
        assert audit.payload_json["from"] == "NEU"
        assert audit.payload_json["to"] == "OFFEN"


async def test_verwalter_public_reply_moves_to_wartet_auf_kunde(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, e_email, e_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    e_token = _login(e_email, e_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(e_token),
            json={"subject": "Status-Test", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        tid = create.json()["id"]
        client.post(
            f"/admin/tickets/{tid}/messages",
            headers=_auth(vw_token),
            json={"body": "Antwort", "is_internal_note": False},
        )
        r = client.get(f"/admin/tickets/{tid}", headers=_auth(vw_token))
    assert r.json()["status"] == "WARTET_AUF_KUNDE"


async def test_eigentuemer_with_contract_sees_co_owner_ticket(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)

    impower_a = 91001
    impower_b = 91002
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_a
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_b
    )

    _user_a, email_a, pw_a = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_a
    )
    _user_b, email_b, pw_b = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_b
    )
    token_a = _login(email_a, pw_a)
    token_b = _login(email_b, pw_b)

    with TestClient(app) as client:
        # share_scope=PROPERTY needed now: default PRIVATE keeps co-owners out.
        create = client.post(
            "/me/tickets",
            headers=_auth(token_a),
            json={
                "subject": "Common laundry room broken",
                "body": "trommel is gone",
                "category": "SCHADEN_ALLGEMEIN",
                "property_id": str(prop.id),
                "share_scope": "PROPERTY",
            },
        )
        assert create.status_code == 201
        ticket_id = create.json()["id"]

        r = client.get(f"/me/tickets/{ticket_id}", headers=_auth(token_b))
    assert r.status_code == 200
    assert r.json()["subject"].startswith("Common laundry")


# --- Participants + share scope ----------------------------------------------


async def test_default_share_scope_is_private(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/tickets",
            headers=_auth(token),
            json={"subject": "Test", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
    assert r.status_code == 201
    assert r.json()["share_scope"] == "PRIVATE"
    assert r.json()["participants"] == []


async def test_creator_can_add_participant_who_then_sees_ticket(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _ea, ea_email, ea_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _eb, eb_email, eb_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(ea_email, ea_pw)
    eb_token = _login(eb_email, eb_pw)

    with TestClient(app) as client:
        # A creates a PRIVATE ticket
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={"subject": "Shared", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        tid = create.json()["id"]

        # B can't see it yet (PRIVATE)
        r = client.get(f"/me/tickets/{tid}", headers=_auth(eb_token))
        assert r.status_code == 404

        # A adds B as participant
        add = client.post(
            f"/me/tickets/{tid}/participants",
            headers=_auth(ea_token),
            json={"email": eb_email},
        )
        assert add.status_code == 201
        assert add.json()["email"] == eb_email

        # B can now see it + reply
        r = client.get(f"/me/tickets/{tid}", headers=_auth(eb_token))
        assert r.status_code == 200
        assert len(r.json()["participants"]) == 1
        reply = client.post(
            f"/me/tickets/{tid}/messages",
            headers=_auth(eb_token),
            json={"body": "B speaking", "is_internal_note": False},
        )
        assert reply.status_code == 201


async def test_remove_participant_revokes_access(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _ea, ea_email, ea_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _eb, eb_email, eb_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(ea_email, ea_pw)
    eb_token = _login(eb_email, eb_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={"subject": "Test ticket", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        tid = create.json()["id"]
        add = client.post(
            f"/me/tickets/{tid}/participants",
            headers=_auth(ea_token),
            json={"email": eb_email},
        )
        user_id_b = add.json()["user_id"]

        # B has access
        assert client.get(f"/me/tickets/{tid}", headers=_auth(eb_token)).status_code == 200

        # A removes B
        rm = client.delete(
            f"/me/tickets/{tid}/participants/{user_id_b}",
            headers=_auth(ea_token),
        )
        assert rm.status_code == 204

        # B no longer has access
        assert client.get(f"/me/tickets/{tid}", headers=_auth(eb_token)).status_code == 404


async def test_non_creator_cannot_add_participants(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _ea, ea_email, ea_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _eb, eb_email, eb_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    _ec, ec_email, ec_pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    ea_token = _login(ea_email, ea_pw)
    eb_token = _login(eb_email, eb_pw)

    with TestClient(app) as client:
        # A creates ticket, adds B (so B has access).
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={"subject": "Test ticket", "body": "Body text", "category": "SONSTIGES_OTHER"},
        )
        tid = create.json()["id"]
        client.post(
            f"/me/tickets/{tid}/participants",
            headers=_auth(ea_token),
            json={"email": eb_email},
        )
        # B (participant, but not creator) tries to add C — should be 403.
        bad = client.post(
            f"/me/tickets/{tid}/participants",
            headers=_auth(eb_token),
            json={"email": ec_email},
        )
        assert bad.status_code == 403
        # Sanity: ec credentials are real
        _ = ec_pw


async def test_share_scope_property_lets_co_owner_see_without_explicit_add(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    impower_a, impower_b = 92001, 92002
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_a
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_b
    )
    _ea, ea_email, ea_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_a
    )
    _eb, eb_email, eb_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_b
    )
    ea_token = _login(ea_email, ea_pw)
    eb_token = _login(eb_email, eb_pw)

    with TestClient(app) as client:
        # PRIVATE — B can't see
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={
                "subject": "Roof leak",
                "body": "Body text",
                "category": "SCHADEN_ALLGEMEIN",
                "property_id": str(prop.id),
            },
        )
        tid = create.json()["id"]
        assert client.get(f"/me/tickets/{tid}", headers=_auth(eb_token)).status_code == 404

        # A widens to PROPERTY — B now sees it (implicit via contract)
        patch = client.patch(
            f"/me/tickets/{tid}/share-scope",
            headers=_auth(ea_token),
            json={"share_scope": "PROPERTY"},
        )
        assert patch.status_code == 200
        assert patch.json()["share_scope"] == "PROPERTY"
        assert client.get(f"/me/tickets/{tid}", headers=_auth(eb_token)).status_code == 200

        # Switching back to PRIVATE removes B's implicit access again.
        client.patch(
            f"/me/tickets/{tid}/share-scope",
            headers=_auth(ea_token),
            json={"share_scope": "PRIVATE"},
        )
        assert client.get(f"/me/tickets/{tid}", headers=_auth(eb_token)).status_code == 404
        _ = eb_pw  # quiet linter


async def test_property_scope_does_not_auto_email_co_owners(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    """Property-scope viewers SEE updates in the portal but do NOT get email
    fan-out on every message (would spam too widely). Only explicit
    participants + creator + Verwalter get notified."""
    org = await make_org(test_engine)
    _vw, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    impower_a, impower_b = 93001, 93002
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_a
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_b
    )
    _, ea_email, ea_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_a
    )
    _, eb_email, _eb_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_b
    )
    ea_token = _login(ea_email, ea_pw)
    vw_token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        # A creates a PROPERTY-scope ticket
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={
                "subject": "Foo",
                "body": "Body text",
                "category": "SCHADEN_ALLGEMEIN",
                "property_id": str(prop.id),
                "share_scope": "PROPERTY",
            },
        )
        tid = create.json()["id"]
        # First email (ticket create) → verwalter only
        assert len(stub_email.sent) == 1
        assert vw_email in stub_email.sent[0]["to"]
        assert eb_email not in stub_email.sent[0]["to"]

        # Verwalter replies public → email goes to creator only, NOT to B
        # (B has property-scope access but isn't an explicit participant)
        client.post(
            f"/admin/tickets/{tid}/messages",
            headers=_auth(vw_token),
            json={"body": "Wir kümmern uns.", "is_internal_note": False},
        )
        assert len(stub_email.sent) == 2
        assert ea_email in stub_email.sent[1]["to"]
        assert eb_email not in stub_email.sent[1]["to"]


async def test_create_with_property_scope_requires_property_id(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, email, pw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.post(
            "/me/tickets",
            headers=_auth(token),
            json={
                "subject": "Test",
                "body": "Body text",
                "category": "SONSTIGES_OTHER",
                "share_scope": "PROPERTY",
                # property_id missing — should 400
            },
        )
    assert r.status_code == 400


# --- Pure model sanity (no HTTP) ---------------------------------------------


async def test_ticket_default_status_is_neu(test_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    org = await make_org(test_engine)
    user, _e, _p = await make_user(test_engine, org=org)
    async with sm() as s:
        t = Ticket(
            organization_id=org.id,
            created_by_user_id=user.id,
            category=TicketCategory.SONSTIGES_OTHER,
            subject="hi",
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        assert t.status == TicketStatus.NEU
        assert t.closed_at is None
        assert t.last_message_at is not None


async def test_share_scope_widen_to_property_notifies_members(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    """Widening an existing ticket to "alle Eigentümer des Objekts" emails
    the property's members ONCE (minus the actor) — repeat PATCHes with the
    same scope stay silent."""
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    impower_a, impower_b = 94001, 94002
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_a
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_b
    )
    _, ea_email, ea_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_a
    )
    _, eb_email, _eb_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_b
    )
    ea_token = _login(ea_email, ea_pw)

    with TestClient(app) as client:
        create = client.post(
            "/me/tickets",
            headers=_auth(ea_token),
            json={
                "subject": "Treppenhauslicht defekt",
                "body": "Body text",
                "category": "SCHADEN_ALLGEMEIN",
                "property_id": str(prop.id),
            },
        )
        tid = create.json()["id"]
        sent_before = len(stub_email.sent)

        r = client.patch(
            f"/me/tickets/{tid}/share-scope",
            headers=_auth(ea_token),
            json={"share_scope": "PROPERTY"},
        )
        assert r.status_code == 200, r.text
        share_mails = stub_email.sent[sent_before:]
        recipients = [m["to"] for m in share_mails]
        assert eb_email in recipients, recipients
        # The actor doesn't get their own announcement.
        assert ea_email not in recipients
        assert any("Freigegebenes Anliegen" in m["subject"] for m in share_mails)

        # Same scope again → no second announcement.
        sent_mid = len(stub_email.sent)
        client.patch(
            f"/me/tickets/{tid}/share-scope",
            headers=_auth(ea_token),
            json={"share_scope": "PROPERTY"},
        )
        assert len(stub_email.sent) == sent_mid
