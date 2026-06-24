# ADR-0016 — Zähler (meter) management with photo-OCR readings

**Status:** accepted
**Date:** 2026-06-24
**Deciders:** Luis Wagner

## Context

Impower has no meter (Zähler) register, and there was no way for owners or
tenants to report Zählerstände (electricity, gas, water, heat). The
Verwalter needs a per-property meter list and an easy reading-capture flow
so the values can be forwarded to suppliers (EnBW etc.) and feed
Betriebskosten-/Heizkostenabrechnung. This is net-new scope (not in
`REQUIREMENTS.md`), hence this ADR.

## Decision

### Data model (two tables, one migration)

- `meters` — Verwalter-created, attached to a `property_id` (required) and
  optionally a `unit_id` (NULL = common/property-wide meter like
  Allgemeinstrom; set = Wohnungs-meter). Carries `meter_type`
  (STROM/GAS/WASSER/WARMWASSER/WAERME/SONSTIGES), free-text `description`
  ("Betriebsstrom"…), `location`, `unit_label` ("kWh"/"m³", defaulted by
  type), `installation_date` + `calibration_valid_until` (Eichfrist), and
  `supplier_name`/`supplier_email`. `is_active` soft-deactivates a swapped
  meter without losing its history.
- `meter_readings` — `value` (Numeric, exact), `read_on`, `source`
  (MANUAL/OCR), `ocr_raw`, optional photo (`local-disk:<suffix>` convention,
  mirrors ticket attachments), `reported_by_user_id`. `forwarded_at` /
  `forwarded_to` are reserved for a future in-app supplier send.

### Who does what

- **Verwalter (admin SPA "Zähler" tab):** create/edit/deactivate meters,
  **bulk-import** a pasted list (`Zählernummer; Typ; Beschreibung` per line),
  review reading history with photos, and **export all readings as CSV**.
- **Any property member (portal "Zähler" tab + iOS):** report a reading —
  ideally by photographing the meter.

### Photo OCR (Gemini multimodal)

`LLMProvider.extract_from_image()` (new) feeds the photo to Gemini as an
inline image part and asks for the numeric reading + Zählernummer as
structured JSON (`MeterReadingOCR`). The suggestion **pre-fills** the value;
the user always confirms/corrects before submitting — we never store an
unconfirmed OCR value. OCR is **never fatal**: an unconfigured provider or an
unreadable photo returns an empty suggestion and the client falls back to
manual entry (mirrors the disabled-when-unconfigured pattern of ADR-0008/0012).
Each OCR call writes one `llm_audit` row.

### v1 scope decisions (per Luis, 2026-06-24)

- **No supplier email send in v1.** Readings + photos are stored; the
  Verwalter exports CSV and forwards out-of-band. `supplier_email` is kept on
  the meter so an in-app send can land later without a migration.
- **No LLM document-extraction to seed meters.** Luis supplies the extracted
  meter list directly, so a paste/CSV **bulk import** covers seeding instead.

## Consequences

- The reading photo lives in our document store under
  `meter_reading_photo_dir`, auth-gated download (never StaticFiles), same
  Hetzner Object Storage migration wave as the other attachment dirs.
- `extract_from_image` is generic — the PDF + image extraction paths now
  share one private `_extract_inline` in the Gemini provider, so a future
  image-OCR feature (e.g. invoice photos) reuses it.
- Member access reuses `_visible_properties_stmt`, so a tenant only sees/
  reports meters on properties they have an active contract on; cross-org
  isolation is covered by a test.
- A meter with readings can't be hard-deleted (409) — deactivate instead, so
  history + photos survive.

## Alternatives considered

- **Auto-forward each reading to the supplier on submit** — rejected for v1:
  an unsupervised outbound email to a third party on every tenant submission
  is risky (wrong readings, spam). Verwalter-reviewed sending is the intended
  follow-up.
- **LLM extraction of meter IDs from supplier PDFs** — deferred; the bulk
  paste import is simpler and Luis already has the numbers extracted.
- **Per-unit-only meters** — rejected; `unit_id` is optional so common
  meters (Allgemeinstrom) and unit meters both fit one model.
