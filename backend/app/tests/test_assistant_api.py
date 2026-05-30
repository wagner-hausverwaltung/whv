"""POST /assistant/query endpoint (ADR-0013). The happy path is covered at
the service level (test_rag_generation.answer_question); here we assert the
endpoint ships dark — 503 while rag_enabled is off (the test default), so it
never touches the RAG store. No RAG_DATABASE_URL needed.
"""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import app
from app.models import UserRole
from app.tests._factories import make_org, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return str(response.json()["access_token"])


async def test_assistant_query_503_when_disabled(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _user, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)

    with TestClient(app) as client:
        response = client.post(
            "/assistant/query",
            json={"question": "Wann ist die nächste Eigentümerversammlung?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 503


def test_assistant_query_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.post("/assistant/query", json={"question": "Hallo?"})
    assert response.status_code == 401
