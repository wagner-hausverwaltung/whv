# ADR-0003: Impower client — hybrid codegen (models generated, client handwritten)

- Date: 2026-05-24
- Status: Accepted
- Supersedes: nothing
- Related: `REQUIREMENTS.md` §7.4

## Context

`REQUIREMENTS.md` §7.4 specifies "OpenAPI client generated from Impower spec (commit generated code so it's reviewable)". Inspecting the live Impower spec at <https://api.app.impower.de/v2/api-docs> shows:

- 67 paths total, of which **20 are relevant to WHV's v1 scope** (properties, units, contracts, contacts, documents, invoices, connections). The remaining 47 are DATEV/EBICS/heating-cost/profit-and-loss/plan-adjustment endpoints that we will never call.
- 134 schemas in `definitions`.
- The spec is **Swagger 2.0**, not OpenAPI 3.0+. The two best Python generators (openapi-python-client for async httpx; datamodel-code-generator for typed models) only accept OpenAPI 3.0+.
- The spec has one broken endpoint (`/v2/heating-cost-reports/import-e-set` uses `type: file`, valid in Swagger 2 but not OpenAPI 3) that survives `swagger2openapi` conversion and trips most generators. It's an endpoint we'll never call.

Going strictly per §7.4 wording (full generated client) would mean ~200 generated `.py` files for endpoints we mostly don't touch, plus a spec-conversion preprocessing step, plus a workaround for the broken endpoint — adding review burden on every PR that touches the integration layer.

## Decision

Adopt a **hybrid codegen** approach:

1. **Pydantic models are generated** from the converted OpenAPI 3 spec using `datamodel-code-generator`, into a single file `backend/app/integrations/impower/_schemas_generated.py`. The file is committed and treated as read-only.
2. **The HTTP client is handwritten** as `backend/app/integrations/impower/client.py` (~180 LOC, async httpx wrapper). Auth, retry, rate-limit awareness, and pagination iterators live here.
3. A small **public re-export module** `schemas.py` exposes the DTOs we actually use; consumers import from there, not from `_schemas_generated`.

A single bash regeneration recipe lives at `infra/scripts/regenerate-impower-schemas.sh` and captures the three steps (Swagger 2 → OpenAPI 3 conversion, datamodel-codegen invocation, post-processing to replace `AwareDatetime` with `datetime` since Impower returns naïve timestamps).

This is a **deliberate deviation from §7.4 wording** but honors its intent: the data shape stays in sync with the spec, the code is reviewable, and the integration surface we own (auth, retry, pagination) is small enough to read in one sitting.

## Consequences

- Adds **2 dev-only build dependencies**: `datamodel-code-generator` (Python, via uv) and `swagger2openapi` (Node, via npx — no permanent install).
- Generated file is ~3,872 lines (200 classes). Ruff and mypy strict checks skip it via `pyproject.toml` excludes.
- Re-running the regeneration is a one-line command — diffs to the generated file are easy to review when Impower updates their spec.
- If Impower's spec adds new endpoints we need, we have two choices: bolt them onto the handwritten client, or (if a sufficient mass accumulates) revisit the full-codegen decision.
- We are coupled to `datamodel-code-generator`'s output style. The post-processing step (`sed` for `AwareDatetime`) is fragile but small enough to inspect.

## Alternatives considered

- **Full generated client via openapi-python-client**: ~200 generated files for the full 67 paths/134 schemas. Most of it dead weight; large diffs on regen; review fatigue.
- **Generate-then-filter the spec**: pre-process the OpenAPI 3 spec to drop unused paths/schemas, then generate. Workable, but adds a custom filter step on top of conversion + generation. We can revisit if the surface grows.
- **Pure handwritten client + handwritten Pydantic models**: 0 generated files. Faster to ship today, but data-shape drift goes undetected if Impower changes a field.
