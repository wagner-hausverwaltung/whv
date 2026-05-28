"""DocuSeal e-signature (ADR-0012): the create/complete service, the
gated create endpoint, and the webhook verify/routing."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.config import get_settings
from app.main import app
from app.models import (
    Document,
    DocumentKind,
    DocumentVisibility,
    SignatureRequestStatus,
    UserRole,
)
from app.services.signatures import (
    complete_signature_request,
    create_signature_request,
)
from app.tests._factories import make_org, make_property, make_user


def _login(email: str, password: str) -> str:
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


@pytest_asyncio.fixture
async def doc_tmp_dir() -> AsyncIterator[Path]:
    """Point the document store at a temp dir so signed-PDF writes don't
    touch /var/lib/whv during tests."""
    with tempfile.TemporaryDirectory(prefix="whv-doc-") as d:
        settings = get_settings()
        original = settings.document_dir
        settings.document_dir = d
        try:
            yield Path(d)
        finally:
            settings.document_dir = original


class _StubDocuSeal:
    is_configured = True

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create_signature_request(
        self,
        *,
        pdf_bytes: bytes,
        filename: str,
        recipient_email: str,
        recipient_name: str | None = None,
    ) -> dict[str, Any]:
        self.created.append({"filename": filename, "email": recipient_email})
        return {"template_id": 11, "submission_id": 22, "raw": {}}

    async def download_document(self, url: str) -> bytes:
        return b"%PDF-1.4 signed"


async def test_create_then_complete_signature_flow(
    test_engine: AsyncEngine, doc_tmp_dir: Path
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    stub = _StubDocuSeal()

    async with sm() as s:
        row = await create_signature_request(
            s,
            organization_id=org.id,
            created_by_user_id=None,
            property_id=prop.id,
            pdf_bytes=b"%PDF-source",
            filename="Vollmacht.pdf",
            recipient_email="signer@example.de",
            recipient_name="Max Mustermann",
            client=cast(Any, stub),
        )
        await s.commit()
        rid = row.id
    assert row.status == SignatureRequestStatus.SENT
    assert row.docuseal_template_id == 11
    assert row.docuseal_submission_id == 22
    assert stub.created == [{"filename": "Vollmacht.pdf", "email": "signer@example.de"}]

    # Completion webhook path: signed PDF stored + linked, status flipped.
    async with sm() as s:
        done = await complete_signature_request(
            s,
            submission_id=22,
            signed_pdf_url="https://sign.example/doc.pdf",
            client=cast(Any, stub),
        )
        await s.commit()
        assert done is not None and done.id == rid
        assert done.status == SignatureRequestStatus.COMPLETED
        assert done.completed_at is not None
        assert done.signed_document_id is not None
        doc = await s.get(Document, done.signed_document_id)

    assert doc is not None
    assert doc.kind == DocumentKind.SIGNATUR
    assert doc.visibility == DocumentVisibility.PRIVATE  # hidden from portal
    assert doc.property_id == prop.id
    # storage_url is set only after write_document succeeds (into doc_tmp_dir).
    assert doc.storage_url is not None and doc.storage_url.startswith("local-disk:")

    # Idempotent: a redelivered webhook returns the same row + doc.
    async with sm() as s:
        again = await complete_signature_request(
            s, submission_id=22, signed_pdf_url="x", client=cast(Any, stub)
        )
        assert again is not None and again.signed_document_id == doc.id


async def test_create_endpoint_503_when_unconfigured(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    _, vemail, vpw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    token = _login(vemail, vpw)
    with TestClient(app) as client:
        r = client.post(
            "/admin/signature-requests?recipient_email=a@b.de",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert r.status_code == 503


async def test_webhook_verifies_signature_and_routes(test_engine: AsyncEngine) -> None:
    settings = get_settings()
    original = settings.docuseal_webhook_secret
    settings.docuseal_webhook_secret = "wh-secret"
    try:
        body = json.dumps(
            {
                "event_type": "form.completed",
                "data": {
                    "submission_id": 999_999,  # no matching row
                    "documents": [{"url": "https://sign.example/y.pdf"}],
                },
            }
        ).encode()
        good = hmac.new(b"wh-secret", body, hashlib.sha256).hexdigest()
        with TestClient(app) as client:
            bad = client.post(
                "/webhooks/docuseal",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Docuseal-Signature": "deadbeef",
                },
            )
            assert bad.status_code == 403

            ok = client.post(
                "/webhooks/docuseal",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Docuseal-Signature": good,
                },
            )
            assert ok.status_code == 200
            # Unknown submission id → routed but no row matched.
            assert ok.json()["status"] == "unknown"
    finally:
        settings.docuseal_webhook_secret = original
