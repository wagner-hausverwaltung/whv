"""Google Gemini implementation of LLMProvider.

The Gemini SDK accepts PDFs inline (base64 data part) up to ~20 MB.
We don't bother with the persistent File API for one-shot extraction
— invitations are <5 MB and the data is uploaded once per call
anyway, no benefit in caching.

Structured output uses `response_mime_type=application/json` plus
`response_schema=Model` (Pydantic). Gemini coerces its own output
to the schema; on miss the SDK raises and the audit layer catches.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.integrations.llm.base import (
    LLMCallStats,
    LLMParseError,
    LLMResult,
)

if TYPE_CHECKING:  # pragma: no cover — only needed for the type-only import
    pass

T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    name: str = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int,
    ) -> None:
        if not api_key:
            # Belt + braces — the factory already guards against this,
            # but constructing the provider directly (e.g. in tests)
            # should fail loud rather than handing back a half-built
            # object that 401s on every call.
            raise ValueError("GeminiProvider requires a non-empty API key")
        self._api_key = api_key
        self._model_name = model
        self._max_output_tokens = max_output_tokens

    async def extract_from_pdf(
        self,
        *,
        pdf_bytes: bytes,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        # Lazy import keeps `import app.integrations.llm` cheap on
        # processes that never make a call (the FastAPI worker, for
        # instance — only Celery actually talks to Gemini).
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
        model = genai.GenerativeModel(  # type: ignore[attr-defined]
            self._model_name,
            generation_config={  # type: ignore[arg-type]
                "response_mime_type": "application/json",
                "response_schema": response_schema,
                "max_output_tokens": self._max_output_tokens,
                # Deterministic-ish: temperature 0 reduces variance on
                # extraction tasks where there's a single right answer.
                "temperature": 0.0,
            },
        )
        started = time.perf_counter()
        response = await model.generate_content_async(
            [
                {"mime_type": "application/pdf", "data": pdf_bytes},
                prompt,
            ]
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # Gemini's SDK returns a top-level `.text` (the JSON string)
        # + a `.usage_metadata` object. Pydantic parses; on schema
        # mismatch we wrap as LLMParseError so the Celery task sees a
        # distinct, non-retryable failure mode.
        try:
            payload = response_schema.model_validate_json(response.text)
        except ValidationError as ve:
            raise LLMParseError(
                f"Gemini response did not match {response_schema.__name__}: {ve}"
            ) from ve

        usage = _coerce_usage(response.usage_metadata)
        stats = LLMCallStats(
            model=self._model_name,
            input_tokens=usage["prompt_token_count"],
            output_tokens=usage["candidates_token_count"],
            latency_ms=elapsed_ms,
        )
        return LLMResult(payload=payload, stats=stats)


def _coerce_usage(meta: Any) -> dict[str, int]:
    """Normalise SDK usage metadata to plain ints. Gemini occasionally
    returns `None` for one of the token counts (multimodal billing
    quirk); we coerce to 0 so the audit row always has numeric values."""
    return {
        "prompt_token_count": int(getattr(meta, "prompt_token_count", 0) or 0),
        "candidates_token_count": int(
            getattr(meta, "candidates_token_count", 0) or 0
        ),
    }
