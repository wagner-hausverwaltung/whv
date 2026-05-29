"""Property hero photos are served by an authenticated endpoint (not a
public StaticFiles mount): GET /admin/property-images/{file} requires a
valid token and is scoped to the caller's org."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.integrations.storage.property_images import property_image_path
from app.main import app
from app.tests._factories import make_org, make_property, make_user


@pytest.fixture
def tmp_property_image_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Point settings.property_image_dir at a per-test tmpdir so the endpoint
    can read real files without touching the default /var/lib path."""
    tmp_dir = tmp_path_factory.mktemp("whv-property-images")
    monkeypatch.setenv("PROPERTY_IMAGE_DIR", str(tmp_dir))
    get_settings.cache_clear()
    try:
        yield str(tmp_dir)
    finally:
        get_settings.cache_clear()


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def test_property_image_requires_auth(tmp_property_image_dir: str) -> None:
    with TestClient(app) as client:
        r = client.get(f"/admin/property-images/{uuid.uuid4()}.png")
    # No token → rejected before we ever touch the filesystem.
    assert r.status_code in (401, 403), r.text


async def test_property_image_served_to_authed_same_org(
    test_engine: AsyncEngine, tmp_property_image_dir: str
) -> None:
    org = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org)
    prop = await make_property(test_engine, org=org, name="Foto Haus")

    # Drop a file on disk where the endpoint will look. Content is opaque to
    # the endpoint (it just FileResponses the bytes).
    path = property_image_path(prop.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x89PNG\r\n\x1a\n-fake-image-bytes"
    path.write_bytes(payload)

    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(
            f"/admin/property-images/{prop.id}.png",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == payload


async def test_property_image_cross_org_404(
    test_engine: AsyncEngine, tmp_property_image_dir: str
) -> None:
    org_a = await make_org(test_engine)
    prop_a = await make_property(test_engine, org=org_a, name="Org A Haus")
    path = property_image_path(prop_a.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bytes")

    # A user from a different org must not be able to read org A's photo,
    # even though the file exists and they know the UUID.
    org_b = await make_org(test_engine)
    _, email, pw = await make_user(test_engine, org=org_b)
    token = _login(email, pw)
    with TestClient(app) as client:
        r = client.get(
            f"/admin/property-images/{prop_a.id}.png",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 404, r.text
