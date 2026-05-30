"""Unit tests for the RAG ingestion building blocks (ADR-0013 §3):
page-aware chunking, the German metadata header, and the Gemini
embedding client (batching + ordering + shape normalisation).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.integrations.llm.base import LLMProviderUnavailableError, NullProvider
from app.integrations.llm.gemini import GeminiProvider
from app.models.document import DocumentKind
from app.rag.chunking import Chunk, chunk_pages
from app.rag.metadata import build_metadata_header, format_eur

# --- chunking ---------------------------------------------------------------


def test_chunk_empty_and_blank_pages() -> None:
    assert chunk_pages([]) == []
    assert chunk_pages(["", "   ", "\n"]) == []


def test_chunk_single_short_page() -> None:
    assert chunk_pages(["Hallo Welt"], target_chars=100, overlap_chars=10) == [
        Chunk(text="Hallo Welt", page=1)
    ]


def test_chunk_overlapping_windows_same_page() -> None:
    out = chunk_pages(["x" * 100], target_chars=40, overlap_chars=10)
    # step = 30 → windows start at 0, 30, 60 (60+40 = 100 = end → stop).
    assert [c.text for c in out] == ["x" * 40, "x" * 40, "x" * 40]
    assert all(c.page == 1 for c in out)


def test_chunk_attributes_page_by_start_offset() -> None:
    out = chunk_pages(["A" * 30, "B" * 30, "C" * 30], target_chars=40, overlap_chars=10)
    assert [c.page for c in out] == [1, 1, 2]


def test_chunk_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        chunk_pages(["x"], target_chars=0)
    with pytest.raises(ValueError):
        chunk_pages(["x"], target_chars=40, overlap_chars=40)


# --- metadata header --------------------------------------------------------


def test_format_eur_is_german() -> None:
    assert format_eur(Decimal("4812.00")) == "4.812,00 €"
    assert format_eur(Decimal("1234567.5")) == "1.234.567,50 €"
    assert format_eur(Decimal("-1234.5")) == "-1.234,50 €"
    assert format_eur(Decimal("0")) == "0,00 €"


def test_build_metadata_header_full() -> None:
    header = build_metadata_header(
        kind=DocumentKind.RECHNUNG,
        contact_name="Mustermann GmbH",
        amount=Decimal("4812.00"),
        issued_date=date(2025, 3, 14),
        property_label="Schmidener Str. 32",
        name="Heizungswartung",
    )
    assert header == (
        "Rechnung · Mustermann GmbH · 4.812,00 € · 2025-03-14 · "
        "Schmidener Str. 32 · Heizungswartung"
    )


def test_build_metadata_header_skips_missing() -> None:
    assert build_metadata_header(kind=DocumentKind.PROTOKOLL) == "Protokoll"


# --- embedding client -------------------------------------------------------


async def test_null_provider_embed_raises() -> None:
    with pytest.raises(LLMProviderUnavailableError):
        await NullProvider().embed_texts(["anything"])


async def test_gemini_embed_empty_returns_empty() -> None:
    provider = GeminiProvider(api_key="k", model="m", max_output_tokens=8)
    assert await provider.embed_texts([]) == []


async def test_gemini_embed_batches_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], str]] = []

    async def fake_embed(*, model: str, content: list[str], task_type: str) -> dict[str, object]:
        calls.append((model, list(content), task_type))
        # one 2-d vector per input, encoding len(text) so order is checkable
        return {"embedding": [[float(len(c)), 1.0] for c in content]}

    monkeypatch.setattr("google.generativeai.configure", lambda **_: None)
    monkeypatch.setattr("google.generativeai.embed_content_async", fake_embed)
    monkeypatch.setattr("app.integrations.llm.gemini._EMBED_BATCH", 2)

    provider = GeminiProvider(api_key="k", model="m", max_output_tokens=8, embedding_model="emb")
    out = await provider.embed_texts(
        ["a", "bb", "ccc", "dddd", "eeeee"], task_type="retrieval_query"
    )

    assert out == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0], [4.0, 1.0], [5.0, 1.0]]
    # batched 2/2/1, embedding model + query task_type forwarded
    assert [len(content) for _, content, _ in calls] == [2, 2, 1]
    assert calls[0][0] == "emb"
    assert calls[0][2] == "retrieval_query"


async def test_gemini_embed_normalises_flat_single(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(*, model: str, content: list[str], task_type: str) -> dict[str, object]:
        # the SDK returns a FLAT vector for a single content item
        assert len(content) == 1
        return {"embedding": [0.5, 0.6, 0.7]}

    monkeypatch.setattr("google.generativeai.configure", lambda **_: None)
    monkeypatch.setattr("google.generativeai.embed_content_async", fake_embed)

    provider = GeminiProvider(api_key="k", model="m", max_output_tokens=8)
    assert await provider.embed_texts(["solo"]) == [[0.5, 0.6, 0.7]]
