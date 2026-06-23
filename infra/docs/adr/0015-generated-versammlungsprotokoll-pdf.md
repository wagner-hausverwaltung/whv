# ADR-0015 — Server-generated Versammlungsprotokoll PDF (WHV design) + e-sign reuse

**Status:** accepted
**Date:** 2026-06-23
**Deciders:** Luis Wagner

## Context

Impower does **not** let us create owner-meeting records (ETV) for
**Mietverwaltungen** (RENTAL properties). The Verwalter still needs a
proper, documentable Versammlung for those — and for any manually-held
meeting — with a branded protocol they can **print + sign by hand** or
send out for **digital signature**.

Until now the signed Protokoll was **upload-only**: the Verwalter
uploaded an externally-produced, already-signed PDF
(`POST /admin/assemblies/{id}/protocol`, see ADR-0007). There was no way
to *produce* the protocol from the structured agenda the portal already
holds (title, TOPs, Beschlusstexte, tallies, Diskussion).

Manual assembly creation already works for **any** property type —
`admin_create_assembly` has no property-type gate and `/me/properties`
returns all org properties to a Verwalter — so RENTAL/Mietverwaltung
Versammlungen need no new write path, only a way to render + sign them.

## Decision

### Generate, don't template: reportlab from the structured agenda

A server-side reportlab generator
(`app/integrations/pdf/assembly_document.py`) renders the
**Versammlungsprotokoll** from the assembly + agenda the DB already
holds. Same library + pattern as the Umlaufbeschluss result PDF
(ADR-0007, `resolution_result.py`) — no new dependency.

- WHV design: brand-blue (`#1863DC`, the app's AccentColor) header band
  with the bundled WAGNER logo (`assets/whv-logo.png`), property +
  address, date/location, the full agenda (each TOP with type,
  Beschlusstext box, result + tally + Stimmrecht), and a signature
  block. Enum values are passed in pre-stringified to German labels so
  the PDF module stays free of SQLAlchemy imports.
- **Not stored.** The PDF is regenerated on demand from the agenda (the
  source of truth) — there is no separate artifact to keep in sync. The
  *signed* PDF that comes back from DocuSeal **is** stored (ADR-0012).

### Two assembly-scoped admin endpoints (reuse ADR-0012 for signing)

- `GET  /admin/assemblies/{id}/document.pdf` — stream the branded PDF for
  preview / download / print.
- `POST /admin/assemblies/{id}/signature-request` — generate the PDF and
  hand its bytes to the **existing** `create_signature_request`
  (ADR-0012). No new signing machinery: the owner is emailed via DocuSeal
  + SES, and the signed PDF is filed under the property on the
  `form.completed` webhook.

### Signature field = a white DocuSeal text-tag in the PDF

DocuSeal's `POST /templates/pdf` builds form fields from **text tags in
the PDF**, not from API-defined coordinates. The generator places a
*white* `{{Unterschrift;type=signature}}` (+ `{{Datum;type=date}}`) on
the signature line: DocuSeal turns it into the signer field, and being
white it leaves no visible artifact if a DocuSeal version doesn't parse
tags. The exact tag→field behaviour shares ADR-0012's "verify against
the deployed version" caveat — DocuSeal is unprovisioned, so this ships
dark and `POST …/signature-request` returns 503 until then. **PDF export
works regardless.**

### Surfaced on both web surfaces (Verwalter-only)

Generation + signing are a Verwalter desk task, exposed in the admin SPA
**and** the owner portal (`MyAssemblyDetailPage`, role-gated) — the
Verwalter browses the owner portal day-to-day. Not in the iOS app.

## Consequences

- The signed Protokoll can now be **produced** in-house (print/sign or
  e-sign), closing the Mietverwaltung documentation gap, while the
  upload path (ADR-0007) stays for externally-signed PDFs.
- The WHV logo is committed to the backend repo
  (`app/integrations/pdf/assets/whv-logo.png`); missing/unreadable →
  the header falls back to a typographic wordmark, never crashes.
- E-sign correctness is bounded by DocuSeal provisioning + the tag
  caveat (shared with ADR-0012) — a one-file fix in the DocuSeal client
  / the PDF tag if the deployed version differs.

## Alternatives considered

- **HTML → PDF (WeasyPrint / headless Chrome)** — nicer CSS, but a new
  heavy dependency (system libs / a browser) for one document. Rejected;
  reportlab is already in the stack.
- **Store the generated PDF** — would drift from the editable agenda.
  Rejected; regenerate from the source of truth, store only the *signed*
  return.
- **Client-side PDF (jsPDF in the SPA)** — font/branding inconsistency
  across browsers + no server path for the e-sign bytes. Rejected.
