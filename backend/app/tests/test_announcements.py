"""Announcement (Mitteilung) tests.

Covers the four corners of the new feature:

  - Lifecycle: create → edit (timer resets while unpublished) →
    publish-now → soft-delete.
  - Scope: admin org-scoped, owner property + audience-role filtered.
  - Attachments: upload + download roundtrip, size cap, extension
    allow-list.
  - Comments + moderation: only after publish, admin hide/unhide
    toggle, hidden invisible to non-admins.
  - Celery publish task: due rows get fan-out, idempotent on a second
    tick.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.integrations.email.client import get_email_client
from app.main import app
from app.models import Announcement, UserRole
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)

# --- fixtures + helpers ----------------------------------------------------


class _StubEmailClient:
    """Captures every Resend send so the Celery publish task can be
    asserted on. Mirrors the EmailClient surface used inside the
    worker — `to`, `subject`, `attachments`. Accepts but ignores all
    other kwargs the production client supports."""

    def __init__(self) -> None:
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
                "attachments": attachments or [],
                "id": msg_id,
            }
        )
        return msg_id

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    """Capture every notification email the request handler fires so
    tests can assert recipients + subjects."""
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


@pytest_asyncio.fixture
async def tmp_announcement_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    """Redirect announcement attachment writes to a tmpdir so
    /var/lib/whv is never touched during tests."""
    tmp_dir = tmp_path_factory.mktemp("whv-announcement-attachments")
    monkeypatch.setenv("ANNOUNCEMENT_ATTACHMENT_DIR", str(tmp_dir))
    get_settings.cache_clear()
    try:
        yield str(tmp_dir)
    finally:
        get_settings.cache_clear()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_eligible_owner(
    engine: AsyncEngine,
    *,
    org: Any,
    prop: Any,
    role: UserRole = UserRole.EIGENTUEMER,
) -> tuple[Any, str, str]:
    """Eigentümer/Mieter/Beirat user wired up to a property via the
    contact → contract chain so `_visible_properties_stmt` resolves
    them. Returns (user, email, password)."""
    impower_id = (uuid.uuid4().int >> 96) + 10**9  # outside realistic range
    await make_contact_with_contract_link(engine, org=org, prop=prop, contact_impower_id=impower_id)
    user, email, pw = await make_user(engine, org=org, role=role, contact_id_impower=impower_id)
    return user, email, pw


# --- Lifecycle: create + 10-min timer + audience validator ----------------


async def test_admin_create_announcement_sets_10min_timer(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    before = datetime.now(UTC)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "Strom aus", "body": "Morgen 9-11 Uhr"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Strom aus"
    assert body["notification_sent_at"] is None  # not yet published
    publish_at = datetime.fromisoformat(body["scheduled_publish_at"])
    delta = publish_at - before
    # Should land within (10 min, 10 min + a few seconds wall-clock slack).
    assert timedelta(minutes=9, seconds=55) <= delta <= timedelta(minutes=10, seconds=10)


async def test_create_rejects_all_false_audience(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={
                "title": "Niemand sieht das",
                "body": "",
                "audience_eigentuemer": False,
                "audience_mieter": False,
                "audience_beirat": False,
            },
        )
    # Pydantic model validator → 422.
    assert r.status_code == 422
    assert "audience" in r.text.lower()


async def test_admin_cannot_target_property_in_other_org(
    test_engine: AsyncEngine,
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    _, a_email, a_pw = await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)
    prop_b = await make_property(test_engine, org=org_b)
    token = _login(a_email, a_pw)
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop_b.id}/announcements",
            headers=_auth(token),
            json={"title": "x", "body": ""},
        )
    assert r.status_code == 404


# --- Edit: timer reset + post-publish frozen + resolved-audience check ----


async def test_update_resets_timer_when_unpublished(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "v1", "body": ""},
        ).json()
        first_publish_at = datetime.fromisoformat(created["scheduled_publish_at"])

        # Sleep a beat so the new scheduled_publish_at is observably
        # later than the original. 1.5s is enough to clear any clock
        # rounding; the test never actually waits for publish.
        import asyncio

        await asyncio.sleep(1.5)

        patched = client.patch(
            f"/admin/announcements/{created['id']}",
            headers=_auth(token),
            json={"title": "v2 — Typo behoben"},
        ).json()
    new_publish_at = datetime.fromisoformat(patched["scheduled_publish_at"])
    assert new_publish_at > first_publish_at
    assert patched["title"] == "v2 — Typo behoben"


async def test_update_keeps_timer_frozen_when_published(
    test_engine: AsyncEngine,
) -> None:
    """Once notification_sent_at is set, edits stick but the publish
    timer doesn't shift — we directly mutate the row to skip the
    Celery hop."""
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "v1", "body": ""},
        ).json()
    # Simulate publish: set notification_sent_at.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(created["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        frozen_at = row.scheduled_publish_at
        await s.commit()

    with TestClient(app) as client:
        patched = client.patch(
            f"/admin/announcements/{created['id']}",
            headers=_auth(token),
            json={"body": "Nachtrag: Wartung verschoben"},
        ).json()
    assert patched["body"] == "Nachtrag: Wartung verschoben"
    assert datetime.fromisoformat(patched["scheduled_publish_at"]) == frozen_at


async def test_update_rejects_all_false_resolved_audience(
    test_engine: AsyncEngine,
) -> None:
    """Patching one flag down to false is fine; patching the last one
    is rejected at the service layer."""
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={
                "title": "test",
                "body": "",
                "audience_eigentuemer": True,
                "audience_mieter": False,
                "audience_beirat": False,
            },
        ).json()
        # Now try to also turn off the last remaining flag.
        r = client.patch(
            f"/admin/announcements/{created['id']}",
            headers=_auth(token),
            json={"audience_eigentuemer": False},
        )
    assert r.status_code == 400
    assert "audience" in r.text.lower()


# --- publish-now + soft delete --------------------------------------------


async def test_publish_now_collapses_timer(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "Notfall", "body": "Wasser stellen wir gleich ab."},
        ).json()
        before = datetime.now(UTC)
        r = client.post(
            f"/admin/announcements/{created['id']}/publish-now",
            headers=_auth(token),
        )
    assert r.status_code == 200
    new_publish_at = datetime.fromisoformat(r.json()["scheduled_publish_at"])
    # After publish-now, scheduled_publish_at should be at or before now.
    assert new_publish_at <= before + timedelta(seconds=2)


async def test_publish_now_409_when_already_published(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "x", "body": ""},
        ).json()
    # Mark published out-of-band.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(created["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        r = client.post(
            f"/admin/announcements/{created['id']}/publish-now",
            headers=_auth(token),
        )
    assert r.status_code == 409


async def test_soft_delete_hides_from_list(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "drop me", "body": ""},
        ).json()
        rd = client.delete(f"/admin/announcements/{created['id']}", headers=_auth(token))
        assert rd.status_code == 204
        # Detail GET should now 404.
        r = client.get(f"/admin/announcements/{created['id']}", headers=_auth(token))
        assert r.status_code == 404
        # List should not include it either.
        rl = client.get(f"/admin/properties/{prop.id}/announcements", headers=_auth(token))
        ids = {item["id"] for item in rl.json()}
        assert created["id"] not in ids


# --- Owner-side: audience filter + published-only -------------------------


async def test_owner_only_sees_published(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, o_email, o_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    o_token = _login(o_email, o_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "Geheim noch", "body": ""},
        ).json()
        # Owner doesn't see it yet — list is empty + detail 404.
        rl = client.get(f"/me/properties/{prop.id}/announcements", headers=_auth(o_token))
        assert rl.status_code == 200
        assert rl.json() == []
        rd = client.get(f"/me/announcements/{created['id']}", headers=_auth(o_token))
        assert rd.status_code == 404
    # Mark published; now the owner can see it.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(created["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        rl2 = client.get(f"/me/properties/{prop.id}/announcements", headers=_auth(o_token))
        assert rl2.status_code == 200
        assert len(rl2.json()) == 1
        assert rl2.json()[0]["id"] == created["id"]


async def test_owner_audience_filter_excludes_wrong_role(
    test_engine: AsyncEngine,
) -> None:
    """A Mieter shouldn't see an Eigentümer-only announcement, even
    if they're on the same property."""
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, m_email, m_pw = await _make_eligible_owner(
        test_engine, org=org, prop=prop, role=UserRole.MIETER
    )
    v_token = _login(v_email, v_pw)
    m_token = _login(m_email, m_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={
                "title": "Eigentümerinfo",
                "body": "",
                "audience_eigentuemer": True,
                "audience_mieter": False,
                "audience_beirat": False,
            },
        ).json()
    # Publish.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(created["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        rl = client.get(f"/me/properties/{prop.id}/announcements", headers=_auth(m_token))
        rd = client.get(f"/me/announcements/{created['id']}", headers=_auth(m_token))
    assert rl.json() == []
    assert rd.status_code == 404


async def test_owner_cross_property_returns_404(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop_a = await make_property(test_engine, org=org)
    prop_b = await make_property(test_engine, org=org)
    _, b_email, b_pw = await _make_eligible_owner(test_engine, org=org, prop=prop_b)
    v_token = _login(v_email, v_pw)
    b_token = _login(b_email, b_pw)
    with TestClient(app) as client:
        created = client.post(
            f"/admin/properties/{prop_a.id}/announcements",
            headers=_auth(v_token),
            json={"title": "Nur A", "body": ""},
        ).json()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(created["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        r = client.get(f"/me/announcements/{created['id']}", headers=_auth(b_token))
    assert r.status_code == 404


# --- Attachments ---------------------------------------------------------


async def test_attachment_upload_download_roundtrip(
    test_engine: AsyncEngine, tmp_announcement_dir: str
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    body = b"%PDF-1.4 fake protocol %EOF"
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "Mit Anhang", "body": ""},
        ).json()
        up = client.post(
            f"/admin/announcements/{ann['id']}/attachments",
            headers=_auth(token),
            files={"file": ("protokoll.pdf", body, "application/pdf")},
        )
        assert up.status_code == 201, up.text
        att = up.json()
        assert att["filename"] == "protokoll.pdf"
        assert att["size_bytes"] == len(body)

        dl = client.get(
            f"/admin/announcements/{ann['id']}/attachments/{att['id']}/download",
            headers=_auth(token),
        )
        assert dl.status_code == 200
        assert dl.content == body


async def test_attachment_rejects_unsupported_extension(
    test_engine: AsyncEngine, tmp_announcement_dir: str
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    token = _login(v_email, v_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(token),
            json={"title": "x", "body": ""},
        ).json()
        r = client.post(
            f"/admin/announcements/{ann['id']}/attachments",
            headers=_auth(token),
            files={
                "file": (
                    "shady.exe",
                    b"MZ\x90\x00 fake binary",
                    "application/octet-stream",
                )
            },
        )
    assert r.status_code == 400


# --- Comments + moderation ------------------------------------------------


async def test_owner_can_comment_after_publish(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, o_email, o_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    o_token = _login(o_email, o_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "Frage zur Mitteilung", "body": ""},
        ).json()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(ann["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        rc = client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(o_token),
            json={"body": "Danke für die Info!"},
        )
        assert rc.status_code == 201
        # Comment appears in detail's comments list.
        rd = client.get(f"/me/announcements/{ann['id']}", headers=_auth(o_token))
    assert rd.status_code == 200
    comments = rd.json()["comments"]
    assert len(comments) == 1
    assert comments[0]["body"] == "Danke für die Info!"
    assert comments[0]["author_email"] == o_email


async def test_owner_cannot_comment_before_publish(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, o_email, o_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    o_token = _login(o_email, o_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "Draft", "body": ""},
        ).json()
        # No publish — owner endpoint should 404 (announcement
        # invisible until published).
        r = client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(o_token),
            json={"body": "should not stick"},
        )
    assert r.status_code == 404


async def test_comment_notifies_verwalter_and_prior_commenters(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    """First comment → only Verwalter is pinged.
    Second comment from a different owner → Verwalter + first commenter."""
    org = await make_org(test_engine)
    v_user, v_email, v_pw = await make_user(
        test_engine, org=org, role=UserRole.VERWALTER
    )
    prop = await make_property(test_engine, org=org)
    _, a_email, a_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    _, b_email, b_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    a_token = _login(a_email, a_pw)
    b_token = _login(b_email, b_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "Topic", "body": ""},
        ).json()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(ann["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()

    with TestClient(app) as client:
        # Owner A comments first. Only the Verwalter should be in
        # the recipient set (no prior commenters yet).
        client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(a_token),
            json={"body": "first reply from A"},
        )
        first_round = [
            entry for entry in stub_email.sent if "Kommentar" in entry["subject"]
        ]
        recipients_first = {to[0] for entry in first_round for to in [entry["to"]]}
        assert recipients_first == {v_user.email}

        # Owner B comments next. Recipients should now be Verwalter
        # + Owner A (the prior non-hidden commenter), but NOT B.
        stub_email.sent.clear()
        client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(b_token),
            json={"body": "second reply from B"},
        )
        second_round = [
            entry for entry in stub_email.sent if "Kommentar" in entry["subject"]
        ]
        recipients_second = {to[0] for entry in second_round for to in [entry["to"]]}
        assert v_email in recipients_second
        assert a_email in recipients_second
        assert b_email not in recipients_second


async def test_author_can_edit_own_comment(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, o_email, o_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    o_token = _login(o_email, o_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "x", "body": ""},
        ).json()
    # Publish out-of-band so commenting is allowed.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(ann["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        c = client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(o_token),
            json={"body": "v1 mit Tippfehler"},
        ).json()
        # Author edits the body — 200 + edited_at populated.
        edit = client.patch(
            f"/me/announcements/{ann['id']}/comments/{c['id']}",
            headers=_auth(o_token),
            json={"body": "v2 ohne Tippfehler"},
        )
        assert edit.status_code == 200, edit.text
        assert edit.json()["body"] == "v2 ohne Tippfehler"
        assert edit.json()["edited_at"] is not None
        # Reload the detail — same body, edited_at carries through.
        d = client.get(f"/me/announcements/{ann['id']}", headers=_auth(o_token))
        assert d.json()["comments"][0]["body"] == "v2 ohne Tippfehler"
        assert d.json()["comments"][0]["edited_at"] is not None


async def test_other_user_cannot_edit_someone_elses_comment(
    test_engine: AsyncEngine,
) -> None:
    """Non-author edit attempt 404s (no existence leak)."""
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, a_email, a_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    _, b_email, b_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    a_token = _login(a_email, a_pw)
    b_token = _login(b_email, b_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "x", "body": ""},
        ).json()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(ann["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        c = client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(a_token),
            json={"body": "von a geschrieben"},
        ).json()
        # b tries to edit a's comment → 404.
        r = client.patch(
            f"/me/announcements/{ann['id']}/comments/{c['id']}",
            headers=_auth(b_token),
            json={"body": "übernommen"},
        )
        assert r.status_code == 404


async def test_admin_hide_comment_removes_from_owner_view(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    _, o_email, o_pw = await _make_eligible_owner(test_engine, org=org, prop=prop)
    v_token = _login(v_email, v_pw)
    o_token = _login(o_email, o_pw)
    with TestClient(app) as client:
        ann = client.post(
            f"/admin/properties/{prop.id}/announcements",
            headers=_auth(v_token),
            json={"title": "x", "body": ""},
        ).json()
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(Announcement, uuid.UUID(ann["id"]))
        assert row is not None
        row.notification_sent_at = datetime.now(UTC)
        await s.commit()
    with TestClient(app) as client:
        c = client.post(
            f"/me/announcements/{ann['id']}/comments",
            headers=_auth(o_token),
            json={"body": "möglicherweise unangemessen"},
        ).json()
        # Admin hides.
        hide = client.patch(
            f"/admin/announcement-comments/{c['id']}",
            headers=_auth(v_token),
            json={"is_hidden": True, "hidden_reason": "Beleidigung"},
        )
        assert hide.status_code == 200
        # Owner detail no longer shows the comment.
        rd = client.get(f"/me/announcements/{ann['id']}", headers=_auth(o_token))
        assert rd.status_code == 200
        assert rd.json()["comments"] == []
        # Admin still sees it on the admin detail.
        ad = client.get(f"/admin/announcements/{ann['id']}", headers=_auth(v_token))
        assert len(ad.json()["comments"]) == 1
        assert ad.json()["comments"][0]["is_hidden"] is True
        # Unhide restores visibility for the owner.
        unhide = client.patch(
            f"/admin/announcement-comments/{c['id']}",
            headers=_auth(v_token),
            json={"is_hidden": False},
        )
        assert unhide.status_code == 200
        rd2 = client.get(f"/me/announcements/{ann['id']}", headers=_auth(o_token))
    assert len(rd2.json()["comments"]) == 1


# --- Celery publish task --------------------------------------------------


async def test_publish_task_fans_out_due_announcements(
    test_engine: AsyncEngine,
    tmp_announcement_dir: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-due rows are skipped; rows past scheduled_publish_at get
    one email per audience-matched recipient + notification_sent_at
    stamped."""
    stub = _StubEmailClient()

    # The Celery task instantiates EmailClient(settings) inline; swap
    # the class so it hands back our stub. asyncio.run also takes
    # care of the lifecycle.
    monkeypatch.setattr("app.workers.tasks.EmailClient", lambda *_a, **_k: stub)

    org = await make_org(test_engine)
    _, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    owner, _, _ = await _make_eligible_owner(test_engine, org=org, prop=prop)

    # Insert an announcement directly with a past scheduled_publish_at
    # so the beat picks it up immediately.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        a = Announcement(
            organization_id=org.id,
            property_id=prop.id,
            created_by_user_id=owner.id,  # any user is fine for FK
            title="Fan-out test",
            body="Hallo Welt",
            audience_eigentuemer=True,
            audience_mieter=True,
            audience_beirat=True,
            scheduled_publish_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        s.add(a)
        await s.commit()
        ann_id = a.id

    from app.workers.tasks import _publish_due_announcements_async

    result = await _publish_due_announcements_async()
    assert result["sent"] >= 1
    assert result["failed"] == 0

    # Owner got their email.
    addresses = {entry["to"][0] for entry in stub.sent if entry["to"]}
    assert owner.email in addresses

    # notification_sent_at stamped → row no longer due.
    async with sm() as s:
        fresh = await s.get(Announcement, ann_id)
        assert fresh is not None
        assert fresh.notification_sent_at is not None


async def test_publish_task_is_idempotent(
    test_engine: AsyncEngine,
    tmp_announcement_dir: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second tick over a row already marked published should be a
    no-op (zero new emails)."""
    stub = _StubEmailClient()
    monkeypatch.setattr("app.workers.tasks.EmailClient", lambda *_a, **_k: stub)

    org = await make_org(test_engine)
    _, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    owner, _, _ = await _make_eligible_owner(test_engine, org=org, prop=prop)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        a = Announcement(
            organization_id=org.id,
            property_id=prop.id,
            created_by_user_id=owner.id,
            title="Once and only once",
            body="",
            audience_eigentuemer=True,
            audience_mieter=True,
            audience_beirat=True,
            scheduled_publish_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        s.add(a)
        await s.commit()

    from app.workers.tasks import _publish_due_announcements_async

    await _publish_due_announcements_async()
    first = len(stub.sent)
    assert first >= 1
    # Second pass — partial index should be empty now.
    await _publish_due_announcements_async()
    assert len(stub.sent) == first
