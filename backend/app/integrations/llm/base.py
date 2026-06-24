"""LLM provider Protocol — the contract every concrete provider
(Gemini today; Anthropic / OpenAI / self-hosted later) implements.

Add methods to the Protocol only when a feature needs them. Today
that's `extract_from_pdf`. Chat + embeddings will land here when
their feature work begins — don't pre-stub them, the YAGNI cost is
real (a half-implemented `chat()` is worse than no chat at all).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True, frozen=True)
class LLMCallStats:
    """Cost + latency telemetry for one LLM call.

    Audit logging writes one row per call using these numbers. Token
    counts are estimates from the provider's usage reporting — exact
    cost calculation lives in the audit layer where we have access to
    per-model pricing tables.
    """

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(slots=True, frozen=True)
class LLMResult[T]:
    """Generic envelope: typed payload + call stats. Concrete `T` is
    the Pydantic model the caller asked the provider to populate."""

    payload: T
    stats: LLMCallStats


class LLMProvider(Protocol):
    """Minimum surface every provider must implement.

    Keep this list as small as the feature set demands. Each addition
    is a stake in the ground that every other provider has to honour.
    """

    name: str
    """Human-readable identifier ("gemini", "anthropic", …) — used by
    the audit table to record which provider answered a given call."""

    async def extract_from_pdf(
        self,
        *,
        pdf_bytes: bytes,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        """Parse a PDF with the given prompt + structured response.

        Implementations MUST validate the response against
        `response_schema` and raise (any concrete exception) on
        parse failure — never return a partial / best-effort
        payload. The Celery wrapper turns failures into a retry +
        audit-log entry; silent partial data would be much worse.
        """
        ...

    async def extract_from_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        """Parse an image (e.g. a meter-face photo) with the given prompt +
        structured response. Same contract as `extract_from_pdf` — validate
        against `response_schema`, raise on parse failure. `mime_type` is the
        image's content type ("image/jpeg", "image/heic", …)."""
        ...

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "retrieval_document",
    ) -> list[list[float]]:
        """Embed each text → a dense vector, one per input, in order.

        Used by the RAG ingestion + retrieval paths (ADR-0013). The
        caller (app.rag) validates dimensionality before persisting.
        `task_type` is the provider's retrieval hint —
        "retrieval_document" at index time, "retrieval_query" at query.
        """
        ...

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """Free-form text generation for the RAG assistant (ADR-0013).

        The caller supplies the full grounded prompt + a system
        instruction; the implementation returns the model's answer text.
        """
        ...


# --- Null implementation ----------------------------------------------------


class NullProvider:
    """No-op provider. Used when `llm_provider=none` or no API key is
    configured. Every call short-circuits with a clear exception so
    the surrounding Celery task can mark the row as "extraction
    skipped — provider not configured" in the audit log and move on.

    Critically, this is NOT a silent success: a NullProvider call
    raises. We want the operator to see why their `--extract`-flagged
    backfill produced zero extractions.
    """

    name: str = "none"

    async def extract_from_pdf(
        self,
        *,
        pdf_bytes: bytes,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        raise LLMProviderUnavailableError(
            "LLM provider not configured (LLM_PROVIDER + GEMINI_API_KEY). Extraction skipped."
        )

    async def extract_from_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        raise LLMProviderUnavailableError(
            "LLM provider not configured (LLM_PROVIDER + GEMINI_API_KEY). OCR skipped."
        )

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "retrieval_document",
    ) -> list[list[float]]:
        raise LLMProviderUnavailableError(
            "LLM provider not configured (LLM_PROVIDER + GEMINI_API_KEY). Embedding skipped."
        )

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        raise LLMProviderUnavailableError(
            "LLM provider not configured (LLM_PROVIDER + GEMINI_API_KEY). Generation skipped."
        )


class LLMProviderUnavailableError(RuntimeError):
    """Raised by NullProvider when an extraction call hits it. The
    Celery task catches this specifically + writes a "skipped" audit
    row rather than retrying — no amount of retries will conjure a
    provider out of an empty config."""


class LLMParseError(RuntimeError):
    """Raised when the model's response can't be coerced into the
    requested schema. Usually means hallucination on a tough document;
    surface it so the Verwalter knows to fall back to manual entry
    rather than silently storing garbage."""
