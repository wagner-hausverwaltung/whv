"""Umlaufbeschluss — eligibility, voting, tally, finalize, beat task.

Covers the moving parts most likely to silently break: the owner-eligibility
join (contracts → contract_contacts → contacts), the two outcome modes
(KLASSISCH unanimous vs. MEHRHEITS majority+quorum), the scope guards on
the owner endpoints, and the finalize pipeline (status flip + PDF write +
result email + audit log) shared by manual close and the Celery beat task.
"""

import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.integrations.email.client import get_email_client
from app.main import app
from app.models import (
    AuditLog,
    CircularResolution,
    CircularVote,
    Organization,
    Property,
    ResolutionMode,
    ResolutionStatus,
    User,
    UserRole,
    VoteChoice,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)

# --- Shared fixtures ---------------------------------------------------------


class _StubEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
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


@pytest_asyncio.fixture
async def pdf_tmp_dir() -> AsyncIterator[Path]:
    """Override the PDF dir so test runs never touch /var/lib/whv."""
    with tempfile.TemporaryDirectory(prefix="whv-pdf-") as d:
        settings = get_settings()
        original = settings.resolution_pdf_dir
        settings.resolution_pdf_dir = d
        try:
            yield Path(d)
        finally:
            settings.resolution_pdf_dir = original


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class _Seed:
    org: Organization
    prop: Property
    verwalter: User
    owner_a: User
    owner_b: User
    outsider: User
    verw_pw: str
    owner_a_pw: str
    owner_b_pw: str
    outsider_pw: str
    impower_a: int
    impower_b: int


def _fresh_impower_id() -> int:
    """Random 32-bit-ish int, unique across tests sharing the same DB."""
    return uuid.uuid4().int >> 96 & 0x7FFFFFFF


async def _seed_two_owners_one_outsider(engine: AsyncEngine) -> _Seed:
    org = await make_org(engine)
    prop = await make_property(engine, org=org)

    verwalter, _verw_email, verw_pw = await make_user(engine, org=org, role=UserRole.VERWALTER)

    impower_a = _fresh_impower_id()
    impower_b = _fresh_impower_id()
    impower_outsider = _fresh_impower_id()

    owner_a, _a_email, owner_a_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_a
    )
    await make_contact_with_contract_link(engine, org=org, prop=prop, contact_impower_id=impower_a)

    owner_b, _b_email, owner_b_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_b
    )
    await make_contact_with_contract_link(engine, org=org, prop=prop, contact_impower_id=impower_b)

    # Outsider — NO contract on this property
    outsider, _o_email, outsider_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_outsider
    )

    return _Seed(
        org=org,
        prop=prop,
        verwalter=verwalter,
        owner_a=owner_a,
        owner_b=owner_b,
        outsider=outsider,
        verw_pw=verw_pw,
        owner_a_pw=owner_a_pw,
        owner_b_pw=owner_b_pw,
        outsider_pw=outsider_pw,
        impower_a=impower_a,
        impower_b=impower_b,
    )


def _now_iso(offset_minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).isoformat()


# --- Create + invitation email ----------------------------------------------


@pytest.mark.asyncio
async def test_create_resolution_fans_out_invitation_email(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    token = _login(seed.verwalter.email, seed.verw_pw)
    body = {
        "property_id": str(seed.prop.id),
        "title": "Sanierung Heizung 2026",
        "description": "Beschluss über die Erneuerung der Heizungsanlage.",
        "mode": "MEHRHEITS",
        "opens_at": _now_iso(-1),  # already open
        "closes_at": _now_iso(60 * 24),  # 24h
        "required_quorum": 2,
    }
    with TestClient(app) as client:
        r = client.post("/admin/resolutions", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["status"] == "OFFEN"
    assert payload["mode"] == "MEHRHEITS"
    assert payload["tally"]["eligible_voters"] == 2

    recipients = sorted(s["to"] for s in stub_email.sent)
    assert recipients == sorted([seed.owner_a.email, seed.owner_b.email])
    assert all("Sanierung Heizung" in s["subject"] for s in stub_email.sent)


@pytest.mark.asyncio
async def test_create_resolution_in_future_stays_entwurf(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    token = _login(seed.verwalter.email, seed.verw_pw)
    body = {
        "property_id": str(seed.prop.id),
        "title": "Zukünftiger Beschluss",
        "description": "Öffnet erst in 2 Tagen.",
        "mode": "KLASSISCH",
        "opens_at": _now_iso(60 * 24 * 2),
        "closes_at": _now_iso(60 * 24 * 5),
        "required_quorum": 0,
    }
    with TestClient(app) as client:
        r = client.post("/admin/resolutions", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ENTWURF"
    # No emails for ENTWURF — owners shouldn't see it yet.
    assert stub_email.sent == []


# --- Scope rules on owner endpoints ------------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_see_resolution(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    v_token = _login(seed.verwalter.email, seed.verw_pw)
    body = {
        "property_id": str(seed.prop.id),
        "title": "Inneres",
        "description": "Nur Eigentümer dieser Liegenschaft.",
        "mode": "MEHRHEITS",
        "opens_at": _now_iso(-1),
        "closes_at": _now_iso(60 * 24),
        "required_quorum": 1,
    }
    with TestClient(app) as client:
        r = client.post("/admin/resolutions", json=body, headers=_auth(v_token))
    resolution_id = r.json()["id"]

    o_token = _login(seed.outsider.email, seed.outsider_pw)
    with TestClient(app) as client:
        r_list = client.get("/me/resolutions", headers=_auth(o_token))
        r_get = client.get(f"/me/resolutions/{resolution_id}", headers=_auth(o_token))
        r_vote = client.post(
            f"/me/resolutions/{resolution_id}/vote",
            json={"choice": "JA"},
            headers=_auth(o_token),
        )
    assert r_list.status_code == 200
    assert r_list.json() == []
    assert r_get.status_code == 404
    assert r_vote.status_code == 404


# --- Vote cast / replace / closed ---------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_cast_then_replace_vote(
    test_engine: AsyncEngine, stub_email: _StubEmailClient
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    v_token = _login(seed.verwalter.email, seed.verw_pw)
    body = {
        "property_id": str(seed.prop.id),
        "title": "Abstimmung A",
        "description": "Eine Beschlussvorlage.",
        "mode": "MEHRHEITS",
        "opens_at": _now_iso(-1),
        "closes_at": _now_iso(60 * 24),
        "required_quorum": 1,
    }
    with TestClient(app) as client:
        r = client.post("/admin/resolutions", json=body, headers=_auth(v_token))
    resolution_id = r.json()["id"]

    a_token = _login(seed.owner_a.email, seed.owner_a_pw)
    with TestClient(app) as client:
        r1 = client.post(
            f"/me/resolutions/{resolution_id}/vote",
            json={"choice": "JA"},
            headers=_auth(a_token),
        )
        r2 = client.post(
            f"/me/resolutions/{resolution_id}/vote",
            json={"choice": "NEIN"},
            headers=_auth(a_token),
        )
        r3 = client.get(f"/me/resolutions/{resolution_id}", headers=_auth(a_token))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 200
    detail = r3.json()
    assert detail["my_vote"]["choice"] == "NEIN"
    # Owners only see their own vote, never the other owner's.
    assert len(detail["votes"]) == 1


# --- Tally + decide outcome --------------------------------------------------


async def _make_open_resolution(
    engine: AsyncEngine,
    org: Organization,
    prop: Property,
    verwalter: User,
    *,
    mode: ResolutionMode,
    required_quorum: int,
    closes_in_minutes: int = 60 * 24,
) -> CircularResolution:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        r = CircularResolution(
            organization_id=org.id,
            property_id=prop.id,
            title=f"R-{uuid.uuid4().hex[:6]}",
            description="seed",
            mode=mode,
            status=ResolutionStatus.OFFEN,
            opens_at=datetime.now(UTC) - timedelta(minutes=1),
            closes_at=datetime.now(UTC) + timedelta(minutes=closes_in_minutes),
            required_quorum=required_quorum,
            created_by=verwalter.id,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
    return r


async def _add_vote(
    engine: AsyncEngine, resolution_id: uuid.UUID, owner_impower: int, choice: VoteChoice
) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            CircularVote(
                resolution_id=resolution_id,
                owner_contact_id_impower=owner_impower,
                choice=choice,
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_close_klassisch_unanimous_yes_passes(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.KLASSISCH,
        required_quorum=0,
    )
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, r.id, seed.impower_b, VoteChoice.JA)

    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        resp = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ANGENOMMEN"
    assert body["tally"]["ja"] == 2
    assert body["tally"]["unanimous_yes"] is True
    assert (pdf_tmp_dir / f"{r.id}.pdf").exists()
    assert any("ANGENOMMEN" in s["subject"] for s in stub_email.sent)
    # Attachment present + non-empty
    assert any(s["attachments"] for s in stub_email.sent)


@pytest.mark.asyncio
async def test_close_klassisch_one_dissent_fails(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.KLASSISCH,
        required_quorum=0,
    )
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, r.id, seed.impower_b, VoteChoice.NEIN)

    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        resp = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ABGELEHNT"


@pytest.mark.asyncio
async def test_close_mehrheits_below_quorum_fails(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.MEHRHEITS,
        required_quorum=2,
    )
    # Only one vote cast — under the quorum of 2.
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)

    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        resp = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ABGELEHNT"
    assert body["tally"]["quorum_met"] is False


@pytest.mark.asyncio
async def test_close_mehrheits_majority_passes(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.MEHRHEITS,
        required_quorum=2,
    )
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, r.id, seed.impower_b, VoteChoice.NEIN)
    # 2 cast, 1 JA, 1 NEIN — quorum met, but ja > cast/2 → 1 > 1 is False → ABGELEHNT
    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        resp = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ABGELEHNT"


# --- Idempotent close --------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.KLASSISCH,
        required_quorum=0,
    )
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, r.id, seed.impower_b, VoteChoice.JA)

    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        r1 = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
        r2 = client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["status"] == r2.json()["status"] == "ANGENOMMEN"

    # Only one audit_log row for the close
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "resolution_closed",
                    AuditLog.target_id == str(r.id),
                )
            )
        ).all()
    assert len(rows) == 1


# --- PDF download visibility -------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_download_owner_sees_own_outsider_404(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    r = await _make_open_resolution(
        test_engine,
        seed.org,
        seed.prop,
        seed.verwalter,
        mode=ResolutionMode.KLASSISCH,
        required_quorum=0,
    )
    await _add_vote(test_engine, r.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, r.id, seed.impower_b, VoteChoice.JA)

    v_token = _login(seed.verwalter.email, seed.verw_pw)
    with TestClient(app) as client:
        client.post(f"/admin/resolutions/{r.id}/close", headers=_auth(v_token))

    a_token = _login(seed.owner_a.email, seed.owner_a_pw)
    o_token = _login(seed.outsider.email, seed.outsider_pw)
    with TestClient(app) as client:
        r_owner = client.get(f"/me/resolutions/{r.id}/result.pdf", headers=_auth(a_token))
        r_outsider = client.get(f"/me/resolutions/{r.id}/result.pdf", headers=_auth(o_token))
    assert r_owner.status_code == 200
    assert r_owner.content.startswith(b"%PDF-")
    assert r_outsider.status_code == 404


# --- Beat task: ENTWURF → OFFEN + expired finalize ---------------------------


@pytest.mark.asyncio
async def test_beat_opens_due_and_finalizes_expired(
    test_engine: AsyncEngine, stub_email: _StubEmailClient, pdf_tmp_dir: Path
) -> None:
    seed = await _seed_two_owners_one_outsider(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        # ENTWURF whose opens_at has passed — beat should flip to OFFEN
        entwurf = CircularResolution(
            organization_id=seed.org.id,
            property_id=seed.prop.id,
            title="Bald offen",
            description="x",
            mode=ResolutionMode.KLASSISCH,
            status=ResolutionStatus.ENTWURF,
            opens_at=datetime.now(UTC) - timedelta(minutes=5),
            closes_at=datetime.now(UTC) + timedelta(days=2),
            required_quorum=0,
            created_by=seed.verwalter.id,
        )
        # OFFEN whose closes_at has passed — beat should finalize
        expired = CircularResolution(
            organization_id=seed.org.id,
            property_id=seed.prop.id,
            title="Abgelaufen",
            description="x",
            mode=ResolutionMode.KLASSISCH,
            status=ResolutionStatus.OFFEN,
            opens_at=datetime.now(UTC) - timedelta(days=2),
            closes_at=datetime.now(UTC) - timedelta(minutes=5),
            required_quorum=0,
            created_by=seed.verwalter.id,
        )
        s.add_all([entwurf, expired])
        await s.commit()
        await s.refresh(entwurf)
        await s.refresh(expired)
    await _add_vote(test_engine, expired.id, seed.impower_a, VoteChoice.JA)
    await _add_vote(test_engine, expired.id, seed.impower_b, VoteChoice.JA)

    # Run the inner async helper directly (no Celery broker needed).
    from app.workers.tasks import _process_due_resolutions_async

    result = await _process_due_resolutions_async()
    assert result["opened"] == 1
    assert result["closed"] == 1
    assert result["failed"] == 0

    async with sm() as s:
        reloaded_entwurf = await s.get(CircularResolution, entwurf.id)
        reloaded_expired = await s.get(CircularResolution, expired.id)
    assert reloaded_entwurf is not None and reloaded_entwurf.status == ResolutionStatus.OFFEN
    assert reloaded_expired is not None and reloaded_expired.status == ResolutionStatus.ANGENOMMEN
    assert reloaded_expired.result_pdf_url is not None
    assert (pdf_tmp_dir / f"{expired.id}.pdf").exists()
