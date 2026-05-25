"""Tests for `pydantic_to_gemini_schema` — the Pydantic-JSON-Schema →
Gemini-Schema translator.

We can't unit-test the actual Gemini call (no API key in CI, costs
money), but we CAN assert that the translated schema contains only
keys Gemini's SDK accepts. The original bug was that Pydantic's
`Field(max_length=…)` emitted `{"maxLength": N}` and the SDK threw
"Unknown field for Schema: maxLength" before Gemini saw the PDF.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.integrations.llm.gemini import (
    _GEMINI_SCHEMA_KEYS,
    pydantic_to_gemini_schema,
)
from app.services.etv_extraction import ExtractedAssembly
from app.services.etv_protocol_extraction import ExtractedProtocol

_BLOCKLIST = frozenset(
    {
        "$ref",
        "$defs",
        "$schema",
        "definitions",
        "default",
        "title",
        "maxLength",
        "minLength",
        "pattern",
        "examples",
        "anyOf",
        "oneOf",
        "allOf",
        "additionalProperties",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "const",
    }
)


def _schema_keyword_keys(node: object) -> set[str]:
    """Collect dict keys that are JSON Schema KEYWORDS — skips field-
    name keys that live inside `properties`, because those are
    user data not schema metadata."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            if k == "properties" and isinstance(v, dict):
                # Don't add field NAMES to the keyword set, but DO
                # recurse into each field's schema.
                for fschema in v.values():
                    out |= _schema_keyword_keys(fschema)
            else:
                out |= _schema_keyword_keys(v)
    elif isinstance(node, list):
        for item in node:
            out |= _schema_keyword_keys(item)
    return out


def test_scrubbed_assembly_schema_strips_disallowed_keys() -> None:
    """ExtractedAssembly is the real-world schema that broke
    extraction in production. Any blocklisted JSON-Schema keyword
    in the scrubbed output means the SDK will reject the schema
    with 'Unknown field for Schema: …' before Gemini sees the PDF."""
    schema = pydantic_to_gemini_schema(ExtractedAssembly)
    keywords = _schema_keyword_keys(schema)
    leaked = keywords & _BLOCKLIST
    assert not leaked, f"Disallowed keys leaked: {leaked}"
    # All surviving keywords must be in the allow-list.
    extra = keywords - _GEMINI_SCHEMA_KEYS
    assert not extra, f"Unknown keys in scrubbed schema: {extra}"
    # Sanity: the agenda_items nested object survived structurally.
    assert schema["type"] == "object"
    assert "agenda_items" in schema["properties"]
    items = schema["properties"]["agenda_items"]
    assert items["type"] == "array"
    assert items["items"]["type"] == "object"
    assert "position" in items["items"]["properties"]


def test_scrubbed_protocol_schema_strips_disallowed_keys() -> None:
    schema = pydantic_to_gemini_schema(ExtractedProtocol)
    keywords = _schema_keyword_keys(schema)
    assert not (keywords & _BLOCKLIST)
    assert not (keywords - _GEMINI_SCHEMA_KEYS)
    assert "agenda_outcomes" in schema["properties"]


def test_anyof_null_collapses_to_nullable_true() -> None:
    """The most common Pydantic pattern: `field: T | None`. Pydantic
    emits this as `{"anyOf": [{"type": T}, {"type": "null"}]}`.
    Gemini doesn't accept `anyOf`; it does accept `nullable: true`."""

    class _M(BaseModel):
        maybe: str | None = None

    schema = pydantic_to_gemini_schema(_M)
    maybe_field = schema["properties"]["maybe"]
    assert "anyOf" not in maybe_field
    assert maybe_field.get("nullable") is True
    assert maybe_field["type"] == "string"


def test_max_length_and_default_are_stripped() -> None:
    """Belt + braces for the specific keys the original bug surfaced."""

    class _M(BaseModel):
        capped: str = Field(max_length=500, description="capped string")
        maybe: str | None = Field(default=None, max_length=10_000)

    schema = pydantic_to_gemini_schema(_M)
    keywords = _schema_keyword_keys(schema)
    for forbidden in ("maxLength", "default", "title", "$defs", "$ref"):
        assert forbidden not in keywords, (
            f"{forbidden} not stripped — Gemini will reject the schema"
        )


def test_enum_field_survives() -> None:
    """Literals + enums map to Gemini's `enum`. Important because
    agenda type discrimination relies on this."""

    class _M(BaseModel):
        kind: Literal["A", "B", "C"]

    schema = pydantic_to_gemini_schema(_M)
    field = schema["properties"]["kind"]
    assert set(field["enum"]) == {"A", "B", "C"}


def test_nested_model_refs_inlined() -> None:
    """Pydantic emits nested models as `$ref` against `$defs`. Gemini
    doesn't resolve refs — we need to inline them."""

    class _Inner(BaseModel):
        value: int

    class _Outer(BaseModel):
        inner: _Inner

    schema = pydantic_to_gemini_schema(_Outer)
    keywords = _schema_keyword_keys(schema)
    assert "$ref" not in keywords
    assert "$defs" not in keywords
    inner = schema["properties"]["inner"]
    assert inner["type"] == "object"
    assert inner["properties"]["value"]["type"] == "integer"
