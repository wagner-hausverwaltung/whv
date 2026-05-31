"""POST /assistant/query endpoint (ADR-0013). The happy path is covered at
the service level (test_rag_generation.answer_question); here we assert the
endpoint ships dark — 503 while rag_enabled is off (the test default), so it
never touches the RAG store. No RAG_DATABASE_URL needed.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.main import app
from app.models import UserRole
from app.rag.generation import Citation
from app.tests._factories import make_org, make_property, make_user


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


async def test_assistant_query_propagates_citation_source_type(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the response must carry each citation's source_type (+
    contact_id/property_id). A master-data card has a SYNTHETIC document_id, so
    if source_type defaults to "document" the SPA tries to download it as a PDF
    → 404 ("Das Dokument konnte nicht geöffnet werden"). Mock answer_question so
    the endpoint never touches the RAG store / Gemini."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    _user, email, password = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(email, password)

    card_id = uuid.uuid5(uuid.NAMESPACE_DNS, "etv-card")
    answer = SimpleNamespace(
        answer="Die letzte Eigentümerversammlung war am 02.02.2026 [1].",
        abstained=False,
        sources=[
            Citation(
                index=1,
                document_id=card_id,
                page=None,
                source_kind="ETV",
                contact_name=None,
                source_type="etv",
                contact_id=None,
                property_id=prop.id,
            )
        ],
        retrieved_document_ids=[card_id],
    )

    @asynccontextmanager
    async def _fake_scope():  # type: ignore[no-untyped-def]
        yield None

    async def _fake_answer(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return answer

    rag_on = get_settings().model_copy(
        update={
            "rag_enabled": True,
            "rag_database_url": "postgresql+asyncpg://rag:rag@localhost/rag",
        }
    )
    monkeypatch.setattr("app.api.v1.assistant.get_settings", lambda: rag_on)
    app.dependency_overrides[get_settings] = lambda: rag_on
    monkeypatch.setattr("app.api.v1.assistant.get_llm_provider", lambda: object())
    monkeypatch.setattr("app.api.v1.assistant.rag_session_scope", _fake_scope)
    monkeypatch.setattr("app.api.v1.assistant.answer_question", _fake_answer)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/assistant/query",
                json={"question": "Wann war die letzte ETV?"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200, response.text
    src = response.json()["sources"][0]
    assert src["source_type"] == "etv"  # not the "document" default
    assert src["property_id"] == str(prop.id)
    assert src["document_id"] == str(card_id)
