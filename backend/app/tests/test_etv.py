"""Eigentümerversammlung — scope + lifecycle + agenda + protocol upload.

Covers the moving parts most likely to silently break:

  - admin Verwalter-only gating across all mutation routes
  - owner scope: only sees assemblies on properties they have a contract on
  - cancelled ABGESAGT rows are hidden from the owner list, visible to admin
  - agenda position UNIQUE within an assembly (409 on collision)
  - BESCHLUSS-only fields rejected on INFORMATION/DISKUSSION rows
  - protocol PDF upload + authenticated download
  - soft-delete makes an assembly disappear from owner + admin reads
"""

from __future__ import annotations

import io
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.main import app
from app.models import (
    Organization,
    Property,
    User,
    UserRole,
)
from app.tests._factories import (
    make_contact_with_contract_link,
    make_org,
    make_property,
    make_user,
)

# --- Fixtures ----------------------------------------------------------------


@pytest_asyncio.fixture
async def etv_tmp_dir() -> AsyncIterator[Path]:
    """Redirect the protocol + invitation storage dirs so test uploads
    don't touch the real /var/lib path. Both share the same scratch
    dir because their filenames don't collide ({assembly_id}.pdf in
    different subtrees)."""
    with tempfile.TemporaryDirectory(prefix="whv-etv-") as d:
        settings = get_settings()
        original_protocol = settings.etv_protocol_dir
        original_invitation = settings.etv_invitation_dir
        settings.etv_protocol_dir = d
        settings.etv_invitation_dir = d
        try:
            yield Path(d)
        finally:
            settings.etv_protocol_dir = original_protocol
            settings.etv_invitation_dir = original_invitation


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _iso(offset_minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).isoformat()


def _fresh_impower_id() -> int:
    return uuid.uuid4().int >> 96 & 0x7FFFFFFF


@dataclass
class _Seed:
    org: Organization
    prop: Property
    other_prop: Property
    verwalter: User
    verwalter_pw: str
    owner: User
    owner_pw: str
    outsider: User
    outsider_pw: str


async def _seed(engine: AsyncEngine) -> _Seed:
    org = await make_org(engine)
    prop = await make_property(engine, org=org)
    other_prop = await make_property(engine, org=org)

    verwalter, _v_email, verwalter_pw = await make_user(engine, org=org, role=UserRole.VERWALTER)
    impower_owner = _fresh_impower_id()
    owner, _o_email, owner_pw = await make_user(
        engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_owner
    )
    await make_contact_with_contract_link(
        engine, org=org, prop=prop, contact_impower_id=impower_owner
    )
    # outsider has a contract on `other_prop` only — must not see `prop`'s
    # assembly.
    impower_outsider = _fresh_impower_id()
    outsider, _x_email, outsider_pw = await make_user(
        engine,
        org=org,
        role=UserRole.EIGENTUEMER,
        contact_id_impower=impower_outsider,
    )
    await make_contact_with_contract_link(
        engine, org=org, prop=other_prop, contact_impower_id=impower_outsider
    )
    return _Seed(
        org=org,
        prop=prop,
        other_prop=other_prop,
        verwalter=verwalter,
        verwalter_pw=verwalter_pw,
        owner=owner,
        owner_pw=owner_pw,
        outsider=outsider,
        outsider_pw=outsider_pw,
    )


def _create_assembly(
    token: str, prop_id: str, *, start_offset_min: int = 60 * 24 * 7
) -> dict[str, object]:
    body = {
        "property_id": prop_id,
        "title": "Ordentliche Eigentümerversammlung 2026",
        "description": "Jährliche Versammlung.",
        "scheduled_start": _iso(start_offset_min),
        "scheduled_end": _iso(start_offset_min + 120),
        "location": "Vereinsheim Königstraße 42, 70173 Stuttgart",
    }
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop_id}/assemblies",
            json=body,
            headers=_auth(token),
        )
    r.raise_for_status()
    data: dict[str, object] = r.json()
    return data


# --- Admin gating ------------------------------------------------------------


@pytest.mark.asyncio
async def test_eigentuemer_cannot_create_assembly(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    token = _login(seed.owner.email, seed.owner_pw)
    body = {
        "property_id": str(seed.prop.id),
        "title": "Owner-attempted",
        "description": "",
        "scheduled_start": _iso(60),
        "scheduled_end": _iso(180),
        "location": "Anywhere",
    }
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{seed.prop.id}/assemblies",
            json=body,
            headers=_auth(token),
        )
    assert r.status_code == 403


# --- Scope rules on owner endpoints -----------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_see_assembly(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    created = _create_assembly(v_token, str(seed.prop.id))

    o_token = _login(seed.outsider.email, seed.outsider_pw)
    with TestClient(app) as client:
        r_list = client.get(f"/me/properties/{seed.prop.id}/assemblies", headers=_auth(o_token))
        r_get = client.get(f"/me/assemblies/{created['id']}", headers=_auth(o_token))
    assert r_list.status_code == 404
    assert r_get.status_code == 404


@pytest.mark.asyncio
async def test_owner_sees_their_property_assembly(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    created = _create_assembly(v_token, str(seed.prop.id))

    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_list = client.get(f"/me/properties/{seed.prop.id}/assemblies", headers=_auth(o_token))
        r_get = client.get(f"/me/assemblies/{created['id']}", headers=_auth(o_token))
    assert r_list.status_code == 200
    assert any(a["id"] == created["id"] for a in r_list.json())
    assert r_get.status_code == 200
    assert r_get.json()["title"] == "Ordentliche Eigentümerversammlung 2026"


# --- Lifecycle: create / update / soft-delete -------------------------------


@pytest.mark.asyncio
async def test_create_rejects_end_before_start(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    bad = {
        "property_id": str(seed.prop.id),
        "title": "Bad timing",
        "description": "",
        "scheduled_start": _iso(120),
        "scheduled_end": _iso(60),  # before start
        "location": "Nirgendwo",
    }
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{seed.prop.id}/assemblies",
            json=bad,
            headers=_auth(v_token),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_status_transition_geplant_to_eingeladen(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    created = _create_assembly(v_token, str(seed.prop.id))
    assert created["status"] == "GEPLANT"

    with TestClient(app) as client:
        r = client.patch(
            f"/admin/assemblies/{created['id']}",
            json={"status": "EINGELADEN"},
            headers=_auth(v_token),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "EINGELADEN"


@pytest.mark.asyncio
async def test_cancelled_assembly_hidden_from_owner(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    created = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        client.patch(
            f"/admin/assemblies/{created['id']}",
            json={"status": "ABGESAGT"},
            headers=_auth(v_token),
        )

    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_list = client.get(f"/me/properties/{seed.prop.id}/assemblies", headers=_auth(o_token))
    assert r_list.status_code == 200
    assert all(a["id"] != created["id"] for a in r_list.json())
    # Admin still sees it
    with TestClient(app) as client:
        r_admin = client.get(f"/admin/properties/{seed.prop.id}/assemblies", headers=_auth(v_token))
    assert any(a["id"] == created["id"] for a in r_admin.json())


@pytest.mark.asyncio
async def test_soft_delete_hides_assembly(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    created = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        r = client.delete(f"/admin/assemblies/{created['id']}", headers=_auth(v_token))
    assert r.status_code == 204

    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_list = client.get(f"/me/properties/{seed.prop.id}/assemblies", headers=_auth(o_token))
        r_get = client.get(f"/me/assemblies/{created['id']}", headers=_auth(o_token))
    assert r_get.status_code == 404
    assert all(a["id"] != created["id"] for a in r_list.json())


# --- Agenda items ----------------------------------------------------------


@pytest.mark.asyncio
async def test_agenda_position_uniqueness(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        r1 = client.post(
            f"/admin/assemblies/{a['id']}/agenda-items",
            json={"position": 1, "type": "INFORMATION", "title": "Begrüßung"},
            headers=_auth(v_token),
        )
        # Second insert at same position → 409
        r2 = client.post(
            f"/admin/assemblies/{a['id']}/agenda-items",
            json={"position": 1, "type": "INFORMATION", "title": "Doppelt"},
            headers=_auth(v_token),
        )
    assert r1.status_code == 201
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_beschluss_only_fields_rejected_on_information(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        r = client.post(
            f"/admin/assemblies/{a['id']}/agenda-items",
            json={
                "position": 1,
                "type": "INFORMATION",
                "title": "Begrüßung",
                # Not allowed for INFORMATION
                "beschluss_text": "should be rejected",
            },
            headers=_auth(v_token),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_agenda_appears_in_detail_with_discussion(test_engine: AsyncEngine) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        r_item = client.post(
            f"/admin/assemblies/{a['id']}/agenda-items",
            json={
                "position": 1,
                "type": "BESCHLUSS",
                "title": "Sanierung Dach",
                "beschluss_text": "Die Eigentümergemeinschaft beschließt …",
                "vote_required_quorum": 5,
            },
            headers=_auth(v_token),
        )
        assert r_item.status_code == 201
        item_id = r_item.json()["id"]

        # Add a tally + discussion
        client.patch(
            f"/admin/agenda-items/{item_id}",
            json={"vote_yes": 8, "vote_no": 2, "vote_abstain": 1, "vote_result": "ANGENOMMEN"},
            headers=_auth(v_token),
        )
        client.post(
            f"/admin/agenda-items/{item_id}/discussion",
            json={
                "position": 1,
                "speaker_label": "Herr Müller (Wo. 4)",
                "content": "Bitte um Klarstellung.",
            },
            headers=_auth(v_token),
        )

    # Owner reads detail — sees the resolution wording, the tally + the discussion.
    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_detail = client.get(f"/me/assemblies/{a['id']}", headers=_auth(o_token))
    assert r_detail.status_code == 200
    detail = r_detail.json()
    assert len(detail["agenda_items"]) == 1
    item = detail["agenda_items"][0]
    assert item["type"] == "BESCHLUSS"
    assert item["vote_yes"] == 8
    assert item["vote_result"] == "ANGENOMMEN"
    assert len(item["discussion"]) == 1
    assert item["discussion"][0]["speaker_label"].startswith("Herr Müller")


# --- Protocol upload --------------------------------------------------------


@pytest.mark.asyncio
async def test_protocol_upload_and_download(test_engine: AsyncEngine, etv_tmp_dir: Path) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    pdf_bytes = b"%PDF-1.4\n% fake protocol body\n%%EOF\n"
    with TestClient(app) as client:
        r_up = client.post(
            f"/admin/assemblies/{a['id']}/protocol",
            files={"file": ("protokoll.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            headers=_auth(v_token),
        )
    assert r_up.status_code == 200, r_up.text
    body = r_up.json()
    assert body["protocol_pdf_url"].endswith(".pdf")
    # Owner can download
    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_dl = client.get(f"/me/assemblies/{a['id']}/protocol", headers=_auth(o_token))
    assert r_dl.status_code == 200
    assert r_dl.content == pdf_bytes
    assert r_dl.headers["content-type"].startswith("application/pdf")


@pytest.mark.asyncio
async def test_protocol_upload_rejects_non_pdf(test_engine: AsyncEngine, etv_tmp_dir: Path) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        r = client.post(
            f"/admin/assemblies/{a['id']}/protocol",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            headers=_auth(v_token),
        )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_invitation_upload_and_download(
    test_engine: AsyncEngine,
    etv_tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verwalter uploads → row stamps url + uploaded_at + extraction
    enqueued; owner downloads via the auth-gated /me endpoint."""
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    # Stub the Celery .delay() so we don't need a worker running.
    # Captures the assembly_id the upload endpoint enqueued for.
    enqueued: list[str] = []

    class _StubTask:
        def delay(self, aid: str) -> None:
            enqueued.append(aid)

    monkeypatch.setattr(
        "app.workers.tasks.extract_etv_metadata",
        _StubTask(),
    )

    pdf_bytes = b"%PDF-1.4\n% fake invitation body\n%%EOF\n"
    with TestClient(app) as client:
        r_up = client.post(
            f"/admin/assemblies/{a['id']}/invitation",
            files={
                "file": (
                    "einladung.pdf",
                    io.BytesIO(pdf_bytes),
                    "application/pdf",
                ),
            },
            headers=_auth(v_token),
        )
    assert r_up.status_code == 200, r_up.text
    body = r_up.json()
    assert body["invitation_pdf_url"].endswith(".pdf")
    assert body["extraction_enqueued"] is True
    assert enqueued == [a["id"]]

    # Owner downloads.
    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_dl = client.get(f"/me/assemblies/{a['id']}/invitation", headers=_auth(o_token))
    assert r_dl.status_code == 200
    assert r_dl.content == pdf_bytes
    assert r_dl.headers["content-type"].startswith("application/pdf")


@pytest.mark.asyncio
async def test_invitation_delete_clears_url(
    test_engine: AsyncEngine,
    etv_tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verwalter deletes uploaded PDF → file gone + row pointers
    cleared; subsequent download is 404."""
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    monkeypatch.setattr(
        "app.workers.tasks.extract_etv_metadata",
        type("S", (), {"delay": staticmethod(lambda _: None)})(),
    )

    with TestClient(app) as client:
        client.post(
            f"/admin/assemblies/{a['id']}/invitation",
            files={
                "file": (
                    "einladung.pdf",
                    io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
                    "application/pdf",
                )
            },
            headers=_auth(v_token),
        )
        r_del = client.delete(
            f"/admin/assemblies/{a['id']}/invitation",
            headers=_auth(v_token),
        )
    assert r_del.status_code == 204

    o_token = _login(seed.owner.email, seed.owner_pw)
    with TestClient(app) as client:
        r_dl = client.get(f"/me/assemblies/{a['id']}/invitation", headers=_auth(o_token))
    assert r_dl.status_code == 404


@pytest.mark.asyncio
async def test_outsider_cannot_download_protocol(
    test_engine: AsyncEngine, etv_tmp_dir: Path
) -> None:
    seed = await _seed(test_engine)
    v_token = _login(seed.verwalter.email, seed.verwalter_pw)
    a = _create_assembly(v_token, str(seed.prop.id))

    with TestClient(app) as client:
        client.post(
            f"/admin/assemblies/{a['id']}/protocol",
            files={"file": ("protokoll.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "application/pdf")},
            headers=_auth(v_token),
        )

    x_token = _login(seed.outsider.email, seed.outsider_pw)
    with TestClient(app) as client:
        r_dl = client.get(f"/me/assemblies/{a['id']}/protocol", headers=_auth(x_token))
    assert r_dl.status_code == 404
