# ADR-0017 — Digitale Vollmacht (ETV proxy) with in-app signature

**Status:** accepted
**Date:** 2026-06-24
**Deciders:** Luis Wagner

## Context

Owners who can't attend an Eigentümerversammlung want to delegate their
vote to a proxy (another owner, the Beirat, the Verwalter). The legal
artifact is a signed Vollmacht. We already ship DocuSeal e-signing
(ADR-0012), but our **Community edition can't create signing templates via
API** (Pro-gated) and that flow is email-only for *external* signers —
neither fits an owner self-serving a proxy from inside the portal/app.

## Decision

### In-app signature, no DocuSeal

The owner grants + signs in one step: they enter the proxy's name (+ an
optional Weisung), **draw their signature** in the portal/app, and submit.
The backend composites the signature image onto a **WHV-design Vollmacht
PDF** (`render_vollmacht_pdf`, reusing the ADR-0015 protocol chrome) and
stores it. This is einfache elektronische Signatur / Textform — sufficient
for a standard WEG proxy unless the Gemeinschaftsordnung demands stricter
form. No DocuSeal, no Pro tier, no external email round-trip.

### Model + flow

- `etv_vollmachten` — one row per (assembly, owner). Snapshots the
  `principal_name` (resolved server-side from the owner's Impower contact,
  not client-supplied — nobody signs under a typed-in name), `proxy_name`,
  optional `scope_note`, `status` (SIGNED/REVOKED), `signed_at`, and the
  generated PDF (`local-disk:` convention, auth-gated download). The drawn
  signature is composited into the PDF and **not stored separately**.
- Only **Eigentümer/Beirat** may grant (they're the voters); Mieter → 403.
- One active Vollmacht per owner per assembly; the owner can **revoke**
  before the meeting, then grant a fresh one.
- The Verwalter gets a **proxy register** per meeting
  (`GET /admin/assemblies/{id}/vollmachten`) with each grantor's email +
  downloadable PDF.

### Endpoints

`POST/GET /me/assemblies/{id}/vollmacht`, `POST /me/vollmachten/{id}/revoke`,
`GET /me/vollmachten/{id}/document.pdf`;
`GET /admin/assemblies/{id}/vollmachten`, `GET /admin/vollmachten/{id}/document.pdf`.

## Consequences

- Self-contained + free; works on Community DocuSeal. If a stricter
  signature ever becomes necessary, the same model can route through
  DocuSeal Pro later without a data migration.
- The signature lives only inside the rendered PDF — simplest to reason
  about for DSGVO (one artifact, auth-gated, deletable with the row).
- Reuses `_visible_properties_stmt` for member access; cross-org isolation
  covered by a test.

## Alternatives considered

- **DocuSeal email flow** — rejected: Pro-gated template creation +
  external-signer-only; an owner would sign via an email link outside the
  app, worse UX, and blocked on Community.
- **Declaration only (no signature image)** — viable Textform, but a drawn
  signature reads as a "real" Vollmacht to owners + the Verwalter and is
  trivially within reach with a canvas, so we went one step further.
