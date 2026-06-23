"""Versammlungsprotokoll PDF (WHV design) + send-for-signature.

Covers the two assembly-scoped admin endpoints added so the Verwalter
can document a (manually created) Versammlung — including for
Mietverwaltungen, where Impower has no ETV — and send the branded
protocol to an owner for e-signature:

  GET  /admin/assemblies/{id}/document.pdf       -> branded PDF bytes
  POST /admin/assemblies/{id}/signature-request  -> DocuSeal request
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.main import app
from app.models import Property, PropertyType, SignatureRequest, UserRole
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_assembly(
    engine: AsyncEngine, token: str, property_id: str, *, with_agenda: bool = True
) -> str:
    """Create an assembly (+ one BESCHLUSS agenda item) via the admin API,
    returning the assembly id."""
    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{property_id}/assemblies",
            json={
                "property_id": property_id,
                "title": "Ordentliche Eigentümerversammlung 2026",
                "description": "Protokoll der Versammlung.",
                "scheduled_start": "2026-04-28T18:00:00+00:00",
                "scheduled_end": "2026-04-28T21:00:00+00:00",
                "location": "Gemeindesaal, Stuttgart",
            },
            headers=_auth(token),
        )
        r.raise_for_status()
        assembly_id = str(r.json()["id"])
        if with_agenda:
            ra = client.post(
                f"/admin/assemblies/{assembly_id}/agenda-items",
                json={
                    "position": 1,
                    "type": "BESCHLUSS",
                    "title": "Beschluss über den Wirtschaftsplan 2026",
                    "body": "Aussprache & Abstimmung. Sonderzeichen: A & B < C.",
                    "beschluss_text": "Der Wirtschaftsplan 2026 wird genehmigt.",
                },
                headers=_auth(token),
            )
            ra.raise_for_status()
    return assembly_id


@pytest.mark.asyncio
async def test_admin_generates_branded_protocol_pdf(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vemail, vpw)
    assembly_id = await _make_assembly(test_engine, token, str(prop.id))

    with TestClient(app) as client:
        r = client.get(f"/admin/assemblies/{assembly_id}/document.pdf", headers=_auth(token))

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "Versammlungsprotokoll" in r.headers.get("content-disposition", "")
    # A real, logo-bearing PDF — not an empty stub.
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 5_000


@pytest.mark.asyncio
async def test_eigentuemer_cannot_generate_protocol_pdf(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    _, oemail, opw = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    vtoken = _login(vemail, vpw)
    assembly_id = await _make_assembly(test_engine, vtoken, str(prop.id), with_agenda=False)

    otoken = _login(oemail, opw)
    with TestClient(app) as client:
        r = client.get(f"/admin/assemblies/{assembly_id}/document.pdf", headers=_auth(otoken))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_signature_request_503_when_docuseal_unconfigured(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vemail, vpw)
    assembly_id = await _make_assembly(test_engine, token, str(prop.id), with_agenda=False)

    with TestClient(app) as client:
        r = client.post(
            f"/admin/assemblies/{assembly_id}/signature-request",
            json={"recipient_email": "owner@example.de", "recipient_name": "Max Mustermann"},
            headers=_auth(token),
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_signature_request_sends_generated_pdf(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vemail, vpw)
    assembly_id = await _make_assembly(test_engine, token, str(prop.id))

    captured: dict[str, Any] = {}

    class _StubDocuSeal:
        is_configured = True

        async def create_signature_request(
            self,
            *,
            pdf_bytes: bytes,
            filename: str,
            recipient_email: str,
            recipient_name: str | None = None,
        ) -> dict[str, Any]:
            captured["pdf_head"] = pdf_bytes[:5]
            captured["pdf_len"] = len(pdf_bytes)
            captured["email"] = recipient_email
            captured["filename"] = filename
            # Unique ids: the test DB is session-scoped and these rows
            # commit, so a shared submission_id would collide with other
            # signature tests' lookups.
            return {"template_id": 70011, "submission_id": 70022, "raw": {}}

    # The endpoint builds the client inline via get_docuseal_client(settings);
    # patch that name in the endpoint's module to inject the stub.
    monkeypatch.setattr("app.api.v1.etv.get_docuseal_client", lambda _settings: _StubDocuSeal())

    with TestClient(app) as client:
        r = client.post(
            f"/admin/assemblies/{assembly_id}/signature-request",
            json={"recipient_email": "owner@example.de", "recipient_name": "Max Mustermann"},
            headers=_auth(token),
        )

    assert r.status_code == 201, r.text
    # The generated branded PDF — not an upload — reached the signer.
    assert captured["pdf_head"] == b"%PDF-"
    assert captured["pdf_len"] > 5_000
    assert captured["email"] == "owner@example.de"
    assert "Versammlungsprotokoll" in captured["filename"]

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.scalars(
                select(SignatureRequest).where(SignatureRequest.docuseal_submission_id == 70022)
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].recipient_email == "owner@example.de"


@pytest.mark.asyncio
async def test_versammlung_can_be_created_for_mietverwaltung(test_engine: AsyncEngine) -> None:
    """The premise: Impower can't create an ETV for a Mietverwaltung, so the
    manual route must accept a RENTAL property (no property-type gate)."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        p = await s.get(Property, prop.id)
        assert p is not None
        p.type = PropertyType.RENTAL
        await s.commit()

    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vemail, vpw)

    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/assemblies",
            json={
                "property_id": str(prop.id),
                "title": "Eigentümerbesprechung Mietobjekt 2026",
                "description": "",
                "scheduled_start": "2026-05-12T17:00:00+00:00",
                "scheduled_end": "2026-05-12T18:30:00+00:00",
                "location": "Vor Ort",
            },
            headers=_auth(token),
        )
    assert r.status_code == 201, r.text
    # And the branded protocol renders for it.
    with TestClient(app) as client:
        pdf = client.get(f"/admin/assemblies/{r.json()['id']}/document.pdf", headers=_auth(token))
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"
