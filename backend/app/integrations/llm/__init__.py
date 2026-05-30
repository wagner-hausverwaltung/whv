"""LLM provider abstraction.

One Protocol (`LLMProvider`) + concrete implementations per vendor.
Feature code (ETV extraction today; chat + RAG + ticket auto-triage
later) talks to the Protocol, never to the SDK directly, so swapping
provider is a one-file change.

Selection happens in `get_llm_provider()` based on the `llm_provider`
setting. Empty / "none" returns a `NullProvider` that records every
call into the audit log but performs no extraction — keeps feature
code shape identical whether the org has DSGVO sign-off on a vendor
yet or not.

Why "Provider" not "Client": chat sessions and embedding caches will
eventually live alongside one-shot extraction calls; "Client" leaks
the request/response pattern, "Provider" doesn't.
"""

from __future__ import annotations

from app.config import get_settings
from app.integrations.llm.base import LLMProvider, NullProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "none" or not settings.gemini_api_key:
        return NullProvider()
    # Lazy import: the Gemini SDK pulls in tensorflow-lite-friendly
    # protobuf wheels that we don't want loaded on a host with the
    # provider disabled (e.g. local dev without a key). EMBEDDING_DIM is
    # imported here too so the embedder produces vectors that fit the RAG
    # store's Vector(EMBEDDING_DIM) column (single source of truth).
    from app.integrations.llm.gemini import GeminiProvider
    from app.rag.constants import EMBEDDING_DIM

    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        max_output_tokens=settings.llm_max_output_tokens,
        embedding_model=settings.rag_embedding_model,
        embedding_dim=EMBEDDING_DIM,
    )


__all__ = ["LLMProvider", "NullProvider", "get_llm_provider"]
