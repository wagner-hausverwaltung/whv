"""Google Gemini implementation of LLMProvider.

The Gemini SDK accepts PDFs inline (base64 data part) up to ~20 MB.
We don't bother with the persistent File API for one-shot extraction
— invitations are <5 MB and the data is uploaded once per call
anyway, no benefit in caching.

Structured output uses `response_mime_type=application/json` plus
`response_schema=…`. Gemini's Schema is a *strict subset* of JSON
Schema, so we can't hand Pydantic's `model_json_schema()` to the
SDK directly — Pydantic emits `default`, `maxLength`, `title`,
`$defs`, `$ref`, `anyOf` patterns the SDK rejects with a
ValueError. We translate Pydantic → Gemini's accepted shape in
`pydantic_to_gemini_schema()` below.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.integrations.llm.base import (
    LLMCallStats,
    LLMParseError,
    LLMResult,
)

T = TypeVar("T", bound=BaseModel)

# gemini-embedding-001 supports single-input embedContent (+ the long-running
# asyncBatchEmbedContent) but NOT the synchronous batchEmbedContents the SDK
# uses when you hand it a list — so we embed one text per call. This caps how
# many of those per-chunk calls run concurrently (RPM-friendly, not serial).
_EMBED_CONCURRENCY = 8


# Keys Gemini's protobuf-backed Schema accepts. Anything outside this
# set raises "Unknown field for Schema: <key>" at call time.
# Source: empirical (the SDK errors are the spec).
_GEMINI_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "format",
        "description",
        "enum",
        "items",
        "nullable",
        "properties",
        "required",
        "propertyOrdering",
        "minItems",
        "maxItems",
    }
)


def pydantic_to_gemini_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Translate a Pydantic v2 model's JSON Schema into Gemini's
    accepted Schema shape.

    Three transformations:
      1. Resolve `$ref` → inline `$defs` entries.
      2. Collapse `{anyOf: [X, {type: "null"}]}` → `X` with
         `nullable: true` (Gemini doesn't support `anyOf` but does
         support per-field `nullable`).
      3. Strip every key not in `_GEMINI_SCHEMA_KEYS` (default,
         maxLength, title, $schema, examples, pattern, etc.).

    The returned dict is what we hand the SDK as `response_schema`.
    Pydantic still validates the *response* against the original
    model (which is more permissive than what we asked Gemini for)
    so we don't lose any constraint enforcement — we just stop
    sending the SDK constraints it can't process.
    """
    raw = model_cls.model_json_schema()
    defs = dict(raw.get("$defs", {})) | dict(raw.get("definitions", {}))
    scrubbed = _scrub(raw, defs)
    # `_scrub` returns Any because it short-circuits non-dict nodes.
    # The top-level Pydantic schema is always a dict, so the cast is
    # safe; explicit assert keeps mypy happy without an outright
    # `# type: ignore`.
    assert isinstance(scrubbed, dict)
    return scrubbed


def _scrub(node: Any, defs: dict[str, Any]) -> Any:
    """Walk a schema *node* (a dict where keys are JSON Schema
    keywords like `type` / `properties` / `description`). Filters
    keys to Gemini's allow-list + recurses with the right semantics
    for each container key:

      - `properties`: values are field-schemas keyed by field NAME.
        Field names are not schema keywords, so we recurse on each
        value without re-filtering the wrapping dict's keys.
      - `items`: value is a single nested schema-node.
      - `enum` / `required`: lists of literal strings — keep as-is.
      - everything else: literal scalar — keep as-is.
    """
    if not isinstance(node, dict):
        return node

    # Resolve a single $ref to its definition body, then re-scrub the
    # result so nested $refs unfold too.
    if "$ref" in node:
        ref = node["$ref"]
        if isinstance(ref, str) and ref.startswith("#/"):
            parts = ref.split("/")[1:]  # skip leading "#"
            target: Any = {"$defs": defs}
            for p in parts:
                target = target.get(p, {}) if isinstance(target, dict) else {}
            # Merge sibling keys (e.g. `description`) over the
            # referenced body so a `{"$ref": ..., "description": "…"}`
            # still keeps its outer description.
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return _scrub(merged, defs)

    # Collapse Pydantic's `T | None` representation.
    if "anyOf" in node and isinstance(node["anyOf"], list):
        options = node["anyOf"]
        null_options = [o for o in options if isinstance(o, dict) and o.get("type") == "null"]
        non_null = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
        if null_options and len(non_null) == 1:
            # First scrub the non-null branch so its own $ref / nested
            # keys are resolved, then layer `nullable: true` + the
            # parent's description / format on top.
            collapsed_inner = _scrub(non_null[0], defs)
            if not isinstance(collapsed_inner, dict):
                return collapsed_inner
            collapsed = {**collapsed_inner, "nullable": True}
            for keep in ("description", "format"):
                if keep in node and keep not in collapsed:
                    collapsed[keep] = node[keep]
            return collapsed
        # anyOf we don't recognise — drop the key; Gemini won't refuse
        # the rest of the schema.
        node = {k: v for k, v in node.items() if k != "anyOf"}

    out: dict[str, Any] = {}
    for k, v in node.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            # `v` is { field_name: field_schema }. Field names are
            # not schema keywords — recurse on each value without
            # filtering them.
            out[k] = {fname: _scrub(fschema, defs) for fname, fschema in v.items()}
        elif k == "items":
            out[k] = _scrub(v, defs)
        elif k in ("enum", "required") and isinstance(v, list):
            # Lists of literal strings — pass through verbatim.
            out[k] = list(v)
        else:
            out[k] = v
    return out


class GeminiProvider:
    name: str = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int,
        embedding_model: str = "models/gemini-embedding-001",
        embedding_dim: int = 768,
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
        self._embedding_model = embedding_model
        # gemini-embedding-001 emits 3072-dim vectors by default; we ask for
        # output_dimensionality so they match the RAG store's Vector(EMBEDDING_DIM)
        # column. Cosine retrieval is scale-invariant, so the truncated (and not
        # re-normalised) MRL vectors are fine without extra normalisation.
        self._embedding_dim = embedding_dim

    async def extract_from_pdf(
        self,
        *,
        pdf_bytes: bytes,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        return await self._extract_inline(
            data=pdf_bytes,
            mime_type="application/pdf",
            prompt=prompt,
            response_schema=response_schema,
        )

    async def extract_from_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        # Gemini is multimodal — an inline image part OCRs the same way a
        # PDF part does. The meter-reading flow hands us a phone photo and
        # asks for the numeric value back as structured JSON.
        return await self._extract_inline(
            data=image_bytes,
            mime_type=mime_type,
            prompt=prompt,
            response_schema=response_schema,
        )

    async def extract_from_text(
        self,
        *,
        text: str,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        # Structured extraction from plain text (e.g. an inbound email body) —
        # no inline blob part, just the instruction + the text.
        return await self._run_structured(
            parts=[prompt, text],
            response_schema=response_schema,
        )

    async def _extract_inline(
        self,
        *,
        data: bytes,
        mime_type: str,
        prompt: str,
        response_schema: type[T],
    ) -> LLMResult[T]:
        """Shared structured-extraction path for any inline blob (PDF or
        image). The public methods differ only in the part's mime_type."""
        return await self._run_structured(
            parts=[{"mime_type": mime_type, "data": data}, prompt],
            response_schema=response_schema,
        )

    async def _run_structured(
        self,
        *,
        parts: list[Any],
        response_schema: type[T],
    ) -> LLMResult[T]:
        """Run a structured (JSON-schema-constrained) generation over `parts`
        (a mix of inline-blob dicts and prompt/text strings) and validate the
        response against `response_schema`."""
        # Lazy import keeps `import app.integrations.llm` cheap on
        # processes that never make a call (the FastAPI worker, for
        # instance — only Celery actually talks to Gemini).
        import google.generativeai as genai

        gemini_schema = pydantic_to_gemini_schema(response_schema)

        genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
        model = genai.GenerativeModel(  # type: ignore[attr-defined]
            self._model_name,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": gemini_schema,
                "max_output_tokens": self._max_output_tokens,
                # Deterministic-ish: temperature 0 reduces variance on
                # extraction tasks where there's a single right answer.
                "temperature": 0.0,
            },
        )
        started = time.perf_counter()
        response = await model.generate_content_async(parts)
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

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "retrieval_document",
    ) -> list[list[float]]:
        if not texts:
            return []
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
        sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

        async def _embed_one(text: str) -> list[float]:
            async with sem:
                resp = await genai.embed_content_async(  # type: ignore[attr-defined]
                    model=self._embedding_model,
                    content=text,
                    task_type=task_type,
                    output_dimensionality=self._embedding_dim,
                )
            # Single-content embedContent returns a flat vector.
            vector: Any = resp["embedding"]
            return [float(x) for x in vector]

        # gather preserves input order regardless of completion order, so the
        # i-th vector still lines up with the i-th text the caller passed.
        return list(await asyncio.gather(*(_embed_one(text) for text in texts)))

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
        model = genai.GenerativeModel(  # type: ignore[attr-defined]
            self._model_name,
            system_instruction=system,
            generation_config={
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            },
        )
        response = await model.generate_content_async(prompt)
        # `.text` raises if the candidate was blocked (safety) or empty; treat
        # that as "no answer" rather than a 500 — the caller already abstains
        # on an empty answer.
        try:
            return str(response.text or "")
        except (ValueError, AttributeError):
            return ""


def _coerce_usage(meta: Any) -> dict[str, int]:
    """Normalise SDK usage metadata to plain ints. Gemini occasionally
    returns `None` for one of the token counts (multimodal billing
    quirk); we coerce to 0 so the audit row always has numeric values."""
    return {
        "prompt_token_count": int(getattr(meta, "prompt_token_count", 0) or 0),
        "candidates_token_count": int(getattr(meta, "candidates_token_count", 0) or 0),
    }
