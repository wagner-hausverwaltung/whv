"""Document folders + uploads (Item 6).

Covers the Verwalter side of /admin/properties/{id}/folders + documents
upload/patch/delete + the authenticated FileResponse download. Scope
isolation: a Verwalter from another org can't reach into this org's
folder/doc tree. Validation: rejecting unsupported file extensions,
non-empty-folder delete blocked, cross-property folder move blocked.

We don't smoke the portal /me/* read endpoints here — they piggy-back
on the same `_visible_properties_stmt` rule that test_me.py already
covers, so the scope test there is the source of truth.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.main import app
from app.models import Document, DocumentFolder, DocumentKind, UserRole
from app.tests._factories import make_org, make_property, make_user


@pytest_asyncio.fixture
async def tmp_doc_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    """Point settings.document_dir at a per-test tmpdir.

    Storage helpers call get_settings() directly (not through FastAPI's
    dep injection), so overriding `app.dependency_overrides[get_settings]`
    wouldn't reach them. Instead we set the env var that pydantic-settings
    reads at instantiation, then clear the lru_cache so the next call
    re-reads the value. Restoring the cache on teardown avoids leaking
    the tmpdir into later tests.
    """
    tmp_dir = tmp_path_factory.mktemp("whv-docs")
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_dir))
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


# --- Folder CRUD --------------------------------------------------------------


async def test_verwalter_can_create_and_list_folders(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        # Create root folder
        r1 = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "Protokolle"},
        )
        assert r1.status_code == 201, r1.text
        root_id = r1.json()["id"]
        assert r1.json()["parent_folder_id"] is None

        # Create child folder
        r2 = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "2025", "parent_folder_id": root_id},
        )
        assert r2.status_code == 201
        assert r2.json()["parent_folder_id"] == root_id

        # List flat
        r3 = client.get(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
        )
        assert r3.status_code == 200
        names = sorted(f["name"] for f in r3.json())
        assert names == ["2025", "Protokolle"]


async def test_folder_move_rejects_cycle(test_engine: AsyncEngine, tmp_doc_dir: str) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        a = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "A"},
        ).json()
        b = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "B", "parent_folder_id": a["id"]},
        ).json()
        # Try to move A under B → cycle: reject.
        r = client.patch(
            f"/admin/folders/{a['id']}",
            headers=_auth(token),
            json={"parent_folder_id": b["id"]},
        )
        assert r.status_code == 400
        assert "yklus" in r.json()["detail"].lower() or "cycle" in r.json()["detail"].lower()


async def test_folder_delete_rejects_non_empty(test_engine: AsyncEngine, tmp_doc_dir: str) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        parent = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "Parent"},
        ).json()
        client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "Child", "parent_folder_id": parent["id"]},
        )
        # Parent has a child → cannot delete.
        r = client.delete(
            f"/admin/folders/{parent['id']}",
            headers=_auth(token),
        )
    assert r.status_code == 409, r.text


# --- Document upload + download ----------------------------------------------


async def test_document_upload_and_download_roundtrip(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    pdf_bytes = b"%PDF-1.4 test fake pdf body %EOF"
    with TestClient(app) as client:
        r_up = client.post(
            f"/admin/properties/{prop.id}/documents",
            headers=_auth(token),
            files={"file": ("hausordnung.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_up.status_code == 201, r_up.text
        doc = r_up.json()
        assert doc["name"] == "hausordnung.pdf"
        assert doc["size_bytes"] == len(pdf_bytes)
        doc_id = doc["id"]

        r_down = client.get(
            f"/admin/documents/{doc_id}/file",
            headers=_auth(token),
        )
        assert r_down.status_code == 200
        assert r_down.content == pdf_bytes


async def test_document_upload_rejects_unsupported_extension(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/documents",
            headers=_auth(token),
            files={"file": ("evil.exe", b"MZ\x00", "application/octet-stream")},
        )
    assert r.status_code == 400, r.text
    assert "exe" in r.json()["detail"].lower()


# --- Scope isolation ----------------------------------------------------------


async def test_verwalter_cannot_see_other_orgs_folders(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org_a)
    _, vw_b_email, vw_b_pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    token_b = _login(vw_b_email, vw_b_pw)

    with TestClient(app) as client:
        # Cross-org property lookup → 404.
        r = client.get(
            f"/admin/properties/{prop_a.id}/folders",
            headers=_auth(token_b),
        )
    assert r.status_code == 404


async def test_verwalter_cannot_download_other_orgs_document(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    org_a = await make_org(test_engine)
    org_b = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org_a)
    _, vw_a_email, vw_a_pw = await make_user(test_engine, org=org_a, role=UserRole.VERWALTER)
    _, vw_b_email, vw_b_pw = await make_user(test_engine, org=org_b, role=UserRole.VERWALTER)
    token_a = _login(vw_a_email, vw_a_pw)
    token_b = _login(vw_b_email, vw_b_pw)

    with TestClient(app) as client:
        r_up = client.post(
            f"/admin/properties/{prop_a.id}/documents",
            headers=_auth(token_a),
            files={"file": ("private.pdf", b"%PDF private %EOF", "application/pdf")},
        )
        doc_id = r_up.json()["id"]

        # Verwalter from org B → 404 on download (same-org check).
        r_down = client.get(
            f"/admin/documents/{doc_id}/file",
            headers=_auth(token_b),
        )
    assert r_down.status_code == 404


# --- Sanity: a freshly-created folder shows up in the model layer too --------


async def test_folder_row_persists_to_db(test_engine: AsyncEngine, tmp_doc_dir: str) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, vw_email, vw_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vw_email, vw_pw)

    with TestClient(app) as client:
        r = client.post(
            f"/admin/properties/{prop.id}/folders",
            headers=_auth(token),
            json={"name": "Stammdaten"},
        )
    folder_id = uuid.UUID(r.json()["id"])

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(DocumentFolder, folder_id)
    assert row is not None
    assert row.name == "Stammdaten"
    assert row.property_id == prop.id
    assert row.organization_id == org.id


# --- Admin document download: Impower on-demand fallback ----------------------


async def test_admin_download_falls_back_to_impower(
    test_engine: AsyncEngine, tmp_doc_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Impower-synced docs have no local bytes (storage_url NULL); the admin
    download endpoint must fetch them from Impower on demand (regression:
    it used to 404 'Datei ist nicht lokal hinterlegt')."""
    org = await make_org(test_engine)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        doc = Document(
            organization_id=org.id,
            property_id=prop.id,
            name="Hausgeldabrechnung 2025",
            kind=DocumentKind.SONSTIGES,
            impower_id=999001,
            storage_url=None,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        doc_id = doc.id

    # The Impower branch only runs when a token is configured; mock the fetch.
    monkeypatch.setenv("IMPOWER_API_TOKEN", "test-token")
    get_settings.cache_clear()

    async def fake_content(_self: object, document_id: int) -> bytes:
        assert document_id == 999001
        return b"%PDF-1.4 impower-bytes"

    monkeypatch.setattr(
        "app.integrations.impower.client.ImpowerClient.download_document_content",
        fake_content,
    )

    token = _login(vemail, vpw)
    with TestClient(app) as client:
        r = client.get(f"/admin/documents/{doc_id}/file", headers=_auth(token))
    # Shared test DB has no rollback — drop this non-null-impower_id doc now so
    # it doesn't bleed into test_impower_sync_documents' exact-match assertion.
    async with sm() as s:
        stale = await s.get(Document, doc_id)
        if stale is not None:
            await s.delete(stale)
            await s.commit()
    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 impower-bytes"
    assert r.headers["content-type"].startswith("application/pdf")


async def test_admin_download_404_when_no_source(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    """No local bytes and no impower_id → clean 404."""
    org = await make_org(test_engine)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        doc = Document(
            organization_id=org.id,
            property_id=prop.id,
            name="ohne Datei",
            kind=DocumentKind.SONSTIGES,
            impower_id=None,
            storage_url=None,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        doc_id = doc.id

    token = _login(vemail, vpw)
    with TestClient(app) as client:
        r = client.get(f"/admin/documents/{doc_id}/file", headers=_auth(token))
    assert r.status_code == 404, r.text


async def test_portal_documents_collapse_impower_duplicates(
    test_engine: AsyncEngine, tmp_doc_dir: str
) -> None:
    """The Impower sync carries identical copies (same name+size, one row
    dated, one not). The /me listing folds them into the dated row with
    duplicate_count — the undated ghost section was pure noise."""
    from datetime import date as _date

    from app.tests._factories import make_contact_with_contract_link, make_document

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=96001)
    _, email, pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=96001
    )

    dated = await make_document(test_engine, org=org, prop=prop, name="Abrechnung 2025.pdf")
    undated = await make_document(test_engine, org=org, prop=prop, name="Abrechnung 2025.pdf")
    other = await make_document(test_engine, org=org, prop=prop, name="Hausordnung.pdf")
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        for did, size, issued in (
            (dated.id, 1000, _date(2025, 6, 1)),
            (undated.id, 1000, None),
            (other.id, 500, None),
        ):
            doc = await s.get(Document, did)
            assert doc is not None
            doc.size_bytes = size
            doc.issued_date = issued
        await s.commit()

    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(f"/me/properties/{prop.id}/documents", headers=_auth(token))
    assert r.status_code == 200, r.text
    rows = r.json()
    by_name: dict[str, list[dict[str, object]]] = {}
    for x in rows:
        by_name.setdefault(x["name"], []).append(x)
    assert len(by_name["Abrechnung 2025.pdf"]) == 1
    winner = by_name["Abrechnung 2025.pdf"][0]
    assert winner["issued_date"] == "2025-06-01"
    assert winner["duplicate_count"] == 2
    assert by_name["Hausordnung.pdf"][0]["duplicate_count"] == 1


async def test_visibility_gates_portal_listing(test_engine: AsyncEngine, tmp_doc_dir: str) -> None:
    """The visibility dropdown is enforced: property-wide PRIVATE docs (SEPA
    mandates) are Verwalter-only; a PRIVATE doc personally pinned to the
    caller stays visible; BEIRAT_ONLY is hidden from plain owners."""
    from app.models import DocumentVisibility
    from app.tests._factories import make_contact_with_contract_link, make_document

    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    contact_a, _contract_a = await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=97001
    )
    await make_contact_with_contract_link(test_engine, org=org, prop=prop, contact_impower_id=97002)
    _, a_email, a_pw = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=97001
    )
    _, v_email, v_pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)

    sepa = await make_document(test_engine, org=org, prop=prop, name="SEPA Mandat Nachbar.pdf")
    own_private = await make_document(
        test_engine, org=org, prop=prop, name="Einzelabrechnung A.pdf", contact=contact_a
    )
    beirat_doc = await make_document(test_engine, org=org, prop=prop, name="Beiratsprotokoll.pdf")
    normal = await make_document(test_engine, org=org, prop=prop, name="Hausordnung 2026.pdf")
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        for did, vis in (
            (sepa.id, DocumentVisibility.PRIVATE),
            (own_private.id, DocumentVisibility.PRIVATE),
            (beirat_doc.id, DocumentVisibility.BEIRAT_ONLY),
            (normal.id, DocumentVisibility.ALL),
        ):
            doc = await s.get(Document, did)
            assert doc is not None
            doc.visibility = vis
        await s.commit()

    a_token = _login(a_email, a_pw)
    v_token = _login(v_email, v_pw)
    with TestClient(app) as client:
        ra = client.get(f"/me/properties/{prop.id}/documents", headers=_auth(a_token))
        rv = client.get(f"/me/properties/{prop.id}/documents", headers=_auth(v_token))
    assert ra.status_code == 200 and rv.status_code == 200
    owner_names = {d["name"] for d in ra.json()}
    verwalter_names = {d["name"] for d in rv.json()}

    assert "SEPA Mandat Nachbar.pdf" not in owner_names  # the leak, closed
    assert "Beiratsprotokoll.pdf" not in owner_names
    assert "Einzelabrechnung A.pdf" in owner_names  # own PRIVATE doc survives
    assert "Hausordnung 2026.pdf" in owner_names
    assert "SEPA Mandat Nachbar.pdf" in verwalter_names  # Verwalter sees all
