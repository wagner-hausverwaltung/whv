from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz() -> None:
    """Requires postgres + redis to be reachable. See README quick start."""
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "deps": {"postgres": True, "redis": True},
    }


def test_cors_preflight_for_portal_origin() -> None:
    """The SPA portal must be able to OPTIONS-preflight the API cross-origin.

    Origin in this test matches the dev default in Settings (localhost:5173).
    Staging uses ADMIN_UI_BASE_URL=https://admin... and
    PORTAL_BASE_URL=https://portal... — both set via env.
    """
    portal_origin = get_settings().portal_base_url
    with TestClient(app) as client:
        response = client.options(
            "/me/properties",
            headers={
                "Origin": portal_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == portal_origin
    assert "GET" in response.headers.get("access-control-allow-methods", "")
    assert "authorization" in response.headers.get(
        "access-control-allow-headers", ""
    ).lower()
