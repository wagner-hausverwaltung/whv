# ADR-0019 — anfragen@ auto-offer generation (template-overlay)

**Status:** accepted (Phase 1 — manual generator); Phase 2 (inbound automation) planned
**Date:** 2026-06-25
**Deciders:** Luis Wagner

## Context

WHV wants prospective clients to email `anfragen@wagner-hausverwaltung.com`
for a WEG- or Mietverwaltungs-Angebot and receive a ready offer back. The
intended end-state: inbound mail → extract the object (address, number of
units, desired start) → fill the matching offer template → reply with the PDF
attached, adapting only the address, the costing, and the start date (term
defaults to 4 years; start defaults to 1 January of next year when unstated).

This is net-new scope (no sales/lead feature in `REQUIREMENTS.md`, which still
reads Phase 1), hence this ADR. The offers are legally binding Angebote.

## Pricing rules (net + 19 % USt)

- **WEG**: 40–50 €/unit/month (default 45; 35 €/unit when > 15 units), floored
  at **270 €/WEG/month**; escalator **+1 €/unit/month each year**. The VDIV
  Mustervertrag prints the *computed flat* monthly figure (§ 8.1 a) and a flat
  whole-WEG yearly bump (§ 8.1 b = units × 1 €), so the generator computes the
  flat numbers from the per-unit rule.
- **MV**: **30 €/unit/month**, +1 €/unit/year (first bump at start + 1 year).

`app/services/offer_pricing.py` is the single source of truth (pure, tested).

## Decision

### Template-overlay, not rebuild

Each offer is produced by **white-out + re-stamping** the per-customer fields
onto the real template PDF (`app/integrations/pdf/offer_overlay.py` +
`offer_document.py`), keeping all other (legal) text verbatim. Field maps were
measured with `pdftotext -bbox` and verified by rasterising the output.

- **WEG** template = the VDIV Deutschland / Haus & Grund *Verwaltervertrag*
  Mustervertrag (April 2022), a third-party copyrighted standard form WHV uses
  as a VDIV member/licensee. It has fixed fill-in slots → clean per-value
  overlay. We do **not** reproduce the form in code; we stamp the real file.
- **MV** template = WHV's own Immobilienverwaltervertrag, with values inline in
  prose → mix of date-token overlay (Helvetica digits are tabular, so a
  DD.MM.YYYY swap never reflows) and centered block-replacement of the
  recipient / representative / salutation / object lines.

Rejected: regenerating both documents in ReportLab — large effort and, for the
VDIV form, accuracy/copyright risk.

### Base assets

PII-free **blanked** base PDFs are committed under
`app/integrations/pdf/assets/offer_templates/` (chosen over loading from object
storage for deployment simplicity). They are derived from real filled offers by
`stamp_pdf(src, *_blanking_fields())`; provenance + the VDIV-licensee basis are
documented in the assets README.

### Reuse of existing infra

- **Send** = Resend (ADR-0004); attachments already proven. A per-call `from`
  override (Phase 2) lets it send as `anfragen@` without changing global mail.
- **Inbound** (Phase 2) = the existing SES→SNS→`/webhooks/email/inbound`
  pipeline, branched on recipient; `anfragen@` is added as a receipt-rule
  recipient (AWS console, ops task). SES sandbox does **not** block this —
  sending is via Resend, and receiving is not sandbox-limited.
- **Extraction** (Phase 2) = Gemini structured extraction modelled on
  `etv_extraction.py` (prompt + Pydantic schema + `llm_audit` row per call).

### Send mode

The user chose **fully automatic send** for Phase 2. Because a misread unit
count or address would otherwise email a signed-looking binding offer, the
auto-send path will be **gated on extraction confidence + required-fields-valid
and guarded by a feature flag with a kill switch**; low-confidence inquiries
route to a manual review queue instead of sending. Phase 1 ships only the
manual generator (`POST /admin/offers/generate`, Verwalter-only) — nothing
sends automatically yet.

## Consequences

- Manual offer generation works today from the Admin "Angebote" page.
- The third-party VDIV form lives (blanked) in the repo; acceptable as licensee
  use, flagged here.
- A field-map is coupled to each template's layout; if WHV revises a template,
  regenerate the base and re-measure the changed coordinates.
- Phase 2 adds: inbound routing + a lead/Anfrage record, Gemini extraction with
  audit, confidence gating + feature flag, Resend `from` override, and a DSGVO
  sub-processor entry for AWS + a signed DPA.
