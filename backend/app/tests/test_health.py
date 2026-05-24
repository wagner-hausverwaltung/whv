from fastapi.testclient import TestClient

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
