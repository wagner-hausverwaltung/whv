# ADR-0008: Gemini as default LLM provider; LLMProvider abstraction for future chat / RAG

- **Status**: Accepted
- **Date**: 2026-05-25
- **Deciders**: Luis
- **Tags**: ai, llm, dsgvo

## Context

We needed structured-data extraction from `OWNERS_MEETING_INVITATION`
PDFs sourced from Impower: actual meeting date (the invitation
`issued_date` is the *letter* date, not the meeting date), location,
and Tagesordnungspunkte with type + body + optional Beschlusstext.

The hard parts of this problem are layout-sensitive (TOP numbering,
"Beschlussvorschlag:" labels, indented sub-items) and template-
variable across Verwalter — exactly the regime where OCR + regex
breaks down and modern multimodal LLMs excel. Cost is negligible at
our volume (~$5/year ongoing).

We also expect to add LLM-driven features over the next 6-18 months:
in-app chat for Eigentümer + Verwalter, a RAG service against the
document corpus (planned in `rag/` per REQUIREMENTS.md §11.1),
auto-categorisation of incoming tickets, draft generation for
Beschlüsse, summarisation of long announcements. The architecture
chosen here has to absorb those without rewriting.

## Decision

1. **Provider: Google Gemini** (`gemini-flash-latest` default,
   overridable to `gemini-pro-latest` via env). Selection rationale:

   - Strong on German legal documents; native multimodal PDF input;
     structured-output via `response_schema=PydanticModel`.
   - AVV with Google Cloud already in place for WHV — DSGVO Art. 28
     basis is settled.
   - Cost-optimised: Flash ≈ €0.001 per 10-page PDF, well inside the
     budget for the projected 50-100 invitations/year ongoing.
   - 1M-token context window absorbs even the longest Jahresabrechnung
     PDFs we'll throw at future RAG features.

2. **No OCR layer.** Multimodal LLMs read PDFs natively. Adding
   Tesseract or AWS Textract before the LLM would degrade quality
   (layout cues lost) and double the moving parts in the pipeline.

3. **Provider abstraction in `app/integrations/llm/`.**
   - `base.LLMProvider` is a `Protocol` (structural typing — every
     concrete impl is a plain class, no inheritance ceremony).
   - Today the Protocol exposes only `extract_from_pdf`. Methods for
     chat (`chat`), embeddings (`embed`), and pure-text generation
     (`generate`) will be added at the same time as the features
     that need them — NOT pre-stubbed, which would force every
     subsequent provider implementation to satisfy unused contracts.
   - `__init__.get_llm_provider()` is the single swap point. Reads
     `llm_provider` + the relevant API key from settings.
   - A `NullProvider` exists for the unconfigured path: it raises
     `LLMProviderUnavailable` on every call, so the surrounding
     Celery task records a clear "skipped" row in the audit log
     rather than silently no-op'ing.

4. **DSGVO Art. 30 audit trail: `llm_audit_log` table.**
   - One row per outbound LLM call, regardless of provider or feature.
   - Stores `purpose` (free-form, e.g. `etv.extract_metadata`),
     `provider`, `model`, token counts, latency, `status`,
     `subject_kind` + `subject_id`. Does NOT store prompt text or
     model output — those either duplicate the source document or
     duplicate the affected row, both of which are recoverable
     without a second copy.
   - Cost dashboard and per-feature spend slicing read from this
     table directly. No external billing-data pipeline.

5. **Triggering: async via Celery.**
   - Extraction is `extract_etv_metadata(assembly_id)` in
     `app/workers/tasks.py`. Triggered today by
     `python -m app.scripts.backfill_etv --extract`; will be wired
     into the Impower document-sync upsert path in a follow-up so
     newly-arrived `OWNERS_MEETING_INVITATION` documents
     auto-extract.
   - `autoretry_for=(Exception,)`, `max_retries=3`, exponential
     backoff. Non-retryable shapes (`LLMProviderUnavailable`,
     `LLMParseError`) record an audit row + return without raising
     — retries can't fix either.
   - Verwalter sign-off is a hard barrier: any assembly with
     `verified_at IS NOT NULL` is a no-op for the task. The model
     never overwrites human-curated data.

## Consequences

### Pros

- Adding a second provider (Anthropic / OpenAI / self-hosted) is one
  new file in `app/integrations/llm/` plus an env flip — no feature-
  code changes anywhere.
- Chat and RAG features will reuse `LLMProvider` + the audit trail;
  cost-dashboard work is also reusable.
- Verwalter trust model is explicit: `auto_extracted_at` vs.
  `verified_at` is what the admin SPA badges off of (`KI-extrahiert ·
  bitte prüfen`).
- Data minimisation: no prompt / output mirror in our DB.

### Cons

- Single-provider lock for now: any Gemini outage takes extraction
  offline. Acceptable — the surrounding stub data (placeholder date
  + "(bitte ergänzen)" location) remains usable, just less precise.
- We pay for vendor token counts, not OCR-style flat per-page. A
  pathological prompt could spike cost; `llm_max_output_tokens` is
  the hard ceiling.
- A misconfigured prompt could silently regress all extractions —
  future commits adding chat / RAG will need a small eval harness
  (input PDF + expected output) before changing `_PROMPT`.

## Alternatives considered

- **OCR + regex parsing** (Tesseract / Textract → regex on extracted
  text). Rejected: brittle on layout changes, no good answer for
  nested agenda items, would need ongoing maintenance per template.
- **OpenAI GPT-4o.** Comparable quality; rejected primarily because
  WHV already has the Google AVV signed and Anthropic / OpenAI DPAs
  would need separate procurement. Easy to add later (one file).
- **Self-hosted Mistral / Llama.** Strongest privacy story but bigger
  ops surface (GPU host, model versioning, eval). Not worth it
  before traffic justifies it; the abstraction lets us migrate
  without feature rewrites.

## Follow-ups

1. Wire `extract_etv_metadata` into the Impower document sync's
   document-upsert path so new invitations auto-extract.
2. Add `KI-extrahiert · bitte prüfen` badge to the admin SPA
   assembly detail; "Bestätigen" button sets `verified_at` +
   `verified_by_user_id`.
3. Per-org token budget cap (reads `SUM(input_tokens + output_tokens)`
   from `llm_audit_log`, refuses calls when over).
4. Eval harness: a handful of known-good PDFs + expected JSON,
   running on every prompt change.
5. When chat or RAG lands, extend the Protocol with the relevant
   method + add Gemini's implementation.
