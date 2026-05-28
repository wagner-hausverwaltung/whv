"""DocuSeal client gating (ADR-0012). The transport path is verified
against the real instance post-provisioning; here we only assert the
ship-dark gate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.docuseal.client import DocuSealClient, DocuSealError


def _settings(base: str = "", key: str = "") -> Any:
    return SimpleNamespace(docuseal_base_url=base, docuseal_api_key=key)


def test_not_configured_without_key_or_url() -> None:
    assert DocuSealClient(_settings()).is_configured is False
    assert DocuSealClient(_settings(base="https://sign.example.com/api")).is_configured is False
    assert DocuSealClient(_settings(key="tok")).is_configured is False


def test_configured_when_both_set() -> None:
    client = DocuSealClient(_settings(base="https://sign.example.com/api", key="tok"))
    assert client.is_configured is True


async def test_create_raises_when_unconfigured() -> None:
    client = DocuSealClient(_settings())
    with pytest.raises(DocuSealError):
        await client.create_signature_request(
            pdf_bytes=b"%PDF-1.4", filename="vertrag.pdf", recipient_email="a@b.de"
        )
