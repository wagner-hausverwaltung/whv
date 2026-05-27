from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import app
from app.models import UserRole
from app.tests._factories import (
    make_contact_with_contract_link,
    make_document,
    make_org,
    make_property,
    make_unit,
    make_user,
)


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


async def test_me_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get("/me")
    assert response.status_code == 401


async def test_me_returns_authenticated_user(test_engine: AsyncEngine) -> None:
    user, email, password = await make_user(test_engine)
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email"] == email
    assert body["role"] == "verwalter"


async def test_me_properties_for_verwalter_returns_all_org_properties(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    p1 = await make_property(test_engine, org=org, name="Aaa Property")
    p2 = await make_property(test_engine, org=org, name="Bbb Property")
    _, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get("/me/properties", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    ids = {p["id"] for p in body}
    assert str(p1.id) in ids
    assert str(p2.id) in ids


async def test_me_properties_for_eigentuemer_scoped_via_contact(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    mine = await make_property(test_engine, org=org, name="Mine")
    not_mine = await make_property(test_engine, org=org, name="Not Mine")
    impower_contact = 9_000_001
    await make_contact_with_contract_link(
        test_engine, org=org, prop=mine, contact_impower_id=impower_contact
    )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get("/me/properties", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()}
    assert ids == {str(mine.id)}
    assert str(not_mine.id) not in ids


async def test_me_properties_for_eigentuemer_with_no_contact_returns_empty(
    test_engine: AsyncEngine,
) -> None:
    _, email, password = await make_user(
        test_engine, role=UserRole.EIGENTUEMER, contact_id_impower=None
    )
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get("/me/properties", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


async def test_me_property_detail_verwalter_sees_any(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="Detail Test Property")
    u1 = await make_unit(test_engine, org=org, prop=prop, unit_hr_id="W01", floor="EG")
    u2 = await make_unit(test_engine, org=org, prop=prop, unit_hr_id="W02", floor="OG")
    _, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{prop.id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(prop.id)
    assert body["name"] == "Detail Test Property"
    unit_ids = {u["id"] for u in body["units"]}
    assert {str(u1.id), str(u2.id)}.issubset(unit_ids)


async def test_me_property_detail_eigentuemer_sees_own_with_units(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org, name="Mine With Units")
    unit = await make_unit(test_engine, org=org, prop=prop, unit_hr_id="W01")
    impower_contact = 9_000_010
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{prop.id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(prop.id)
    assert {u["id"] for u in body["units"]} == {str(unit.id)}


async def test_me_property_detail_eigentuemer_other_property_returns_404(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    mine = await make_property(test_engine, org=org)
    not_mine = await make_property(test_engine, org=org)
    impower_contact = 9_000_011
    await make_contact_with_contract_link(
        test_engine, org=org, prop=mine, contact_impower_id=impower_contact
    )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{not_mine.id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404


async def test_me_property_detail_unknown_id_returns_404(test_engine: AsyncEngine) -> None:
    import uuid

    _, email, password = await make_user(test_engine, role=UserRole.VERWALTER)
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404


async def test_me_property_detail_eigentuemer_no_contact_returns_404(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=None
    )
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{prop.id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 404


async def test_me_property_documents_verwalter_sees_all(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    d1 = await make_document(test_engine, org=org, prop=prop, name="Aaa.pdf")
    d2 = await make_document(test_engine, org=org, prop=prop, name="Bbb.pdf")
    _, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{prop.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    assert {str(d1.id), str(d2.id)}.issubset(ids)


async def test_me_property_documents_eigentuemer_sees_own_property_docs(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    doc = await make_document(test_engine, org=org, prop=prop, name="Jahresabrechnung.pdf")
    impower_contact = 9_000_020
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=impower_contact
    )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{prop.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    assert str(doc.id) in ids


async def test_me_property_documents_eigentuemer_other_property_returns_404(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    mine = await make_property(test_engine, org=org)
    not_mine = await make_property(test_engine, org=org)
    await make_document(test_engine, org=org, prop=not_mine)
    impower_contact = 9_000_021
    await make_contact_with_contract_link(
        test_engine, org=org, prop=mine, contact_impower_id=impower_contact
    )
    _, email, password = await make_user(
        test_engine, org=org, role=UserRole.EIGENTUEMER, contact_id_impower=impower_contact
    )
    token = _login(email, password)
    with TestClient(app) as client:
        response = client.get(
            f"/me/properties/{not_mine.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404


async def test_me_property_documents_mieter_cannot_see_other_units_doc(
    test_engine: AsyncEngine,
) -> None:
    """A Mieter on Unit 4 must NOT see a doc Impower pinned to Unit 1.

    Property-wide docs (all row-scope FKs NULL) and docs pinned to the
    Mieter's own unit stay visible — the filter hides only the
    cross-unit leakage. Mirrors the Impower scoping that the sync
    pulls into `documents.unit_id`.
    """
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    unit_one = await make_unit(test_engine, org=org, prop=prop, unit_hr_id="W01")
    unit_four = await make_unit(test_engine, org=org, prop=prop, unit_hr_id="W04")

    # Mieter is on Unit 4 via their contract; nothing on Unit 1.
    impower_contact = 9_000_030
    await make_contact_with_contract_link(
        test_engine,
        org=org,
        prop=prop,
        contact_impower_id=impower_contact,
        unit=unit_four,
    )

    visible_doc = await make_document(
        test_engine, org=org, prop=prop, name="Hausordnung.pdf"
    )
    own_unit_doc = await make_document(
        test_engine,
        org=org,
        prop=prop,
        name="Mein-Mietvertrag.pdf",
        unit=unit_four,
    )
    other_unit_doc = await make_document(
        test_engine,
        org=org,
        prop=prop,
        name="Fremder-Mietvertrag.pdf",
        unit=unit_one,
    )

    _, email, password = await make_user(
        test_engine,
        org=org,
        role=UserRole.MIETER,
        contact_id_impower=impower_contact,
    )
    token = _login(email, password)

    with TestClient(app) as client:
        list_response = client.get(
            f"/me/properties/{prop.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Verify the deep-link route is gated the same way: even with
        # the doc id in hand, a Mieter on Unit 4 can't pull bytes for
        # Unit 1's doc.
        deep_link_response = client.get(
            f"/me/documents/{other_unit_doc.id}/file",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert list_response.status_code == 200
    ids = {d["id"] for d in list_response.json()}
    assert str(visible_doc.id) in ids
    assert str(own_unit_doc.id) in ids
    assert str(other_unit_doc.id) not in ids
    assert deep_link_response.status_code == 404
