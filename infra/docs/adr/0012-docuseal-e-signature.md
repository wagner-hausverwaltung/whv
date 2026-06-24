# ADR-0012 — Digital signatures via self-hosted DocuSeal (email-only, SES)

**Status:** accepted
**Date:** 2026-05-28
**Deciders:** Luis Wagner

## Context

The Verwalter needs to send documents (Verträge, Vollmachten,
Beschluss-Umsetzungen …) out for legally-usable digital signature:
pick a document, choose a recipient, and let the recipient sign by
**email only** — no WHV-portal account, no portal reference. Mails must
go out **from the Wagner-Hausverwaltung sender** through our existing
AWS SES.

## Decision

### Service: self-hosted DocuSeal (open-source)

DocuSeal (MIT) over Documenso (AGPL): API-first, dead-simple Docker
self-host, native custom-SMTP so its outbound mail routes through our
SES. Self-hosted (not cloud) keeps signer PII + signed PDFs on our
Hetzner box — no extra DSGVO data processor.

### Flow

1. Admin SPA "Signaturen" tab: upload a PDF, pick a recipient
   (Eigentümer/Kontakt dropdown **or** free-text name+email), submit.
2. Backend `POST /admin/signature-requests` → `DocuSealClient` creates a
   template from the PDF then a submission with the submitter; DocuSeal
   emails the signer **via our SES SMTP** (sender =
   wagner-hausverwaltung). A `signature_requests` row tracks status.
3. Signer signs on DocuSeal's hosted page (email link only — never the
   portal).
4. DocuSeal calls `POST /webhooks/docuseal` (HMAC-verified) on
   `form.completed`; we fetch the signed PDF and **store it in WHV's
   document store** (decision 2026-05-28) + flip the row to `COMPLETED`
   and link the stored document. Impower master data is never touched.

### Disabled-when-unconfigured

Empty `DOCUSEAL_API_KEY` → `DocuSealClient.is_configured` is False and
the create endpoint returns 503 / the feature is hidden. Mirrors the
APNs + Resend pattern: the code ships dark and activates once the
instance + key exist, so nothing breaks before provisioning.

## Consequences

- **Operator prerequisites (one-time, Luis):**
  1. Deploy DocuSeal (Docker) on the Hetzner host; expose via Caddy at
     e.g. `sign.wagner-hausverwaltung.com` (DNS A record).
  2. Create **AWS SES SMTP credentials** and configure them as
     DocuSeal's SMTP so signing mails send from
     `noreply@wagner-hausverwaltung.com`.
  3. Generate a DocuSeal **API token**; set a shared
     **webhook secret**.
  4. Set on the backend: `DOCUSEAL_BASE_URL`, `DOCUSEAL_API_KEY`,
     `DOCUSEAL_WEBHOOK_SECRET`. Point DocuSeal's webhook at
     `https://staging.api.wagner-hausverwaltung.com/webhooks/docuseal`.
- **DocuSeal API shape** (assumed from the documented public API; verify
  against the deployed version): `X-Auth-Token` header;
  `POST /templates/pdf` (base64 PDF → template); `POST /submissions`
  (`template_id` + `submitters[{email,name}]`, `send_email: true`);
  webhook event `form.completed` carrying the signed
  `documents[].url`. The client centralises these so a version drift is
  a one-file fix.
- **Signed PDFs live in our document store** — auditable + visible. We
  store them under a dedicated `SIGNATUR` document kind / folder.
- **No portal exposure for signers** — they're not users; the row is
  admin-only. Matches "email only, no portal reference".

## Alternatives considered

- **Documenso** — more polished UI, but AGPL (copyleft obligations) and
  heavier to run. Rejected for a back-office signing tool.
- **DocuSign / cloud DocuSeal** — adds a data processor + signer PII off
  our infra; unnecessary for our volume. Rejected.
- **Build signing ourselves** — legally + cryptographically risky;
  never reinvent e-signature. Rejected.

## Update 2026-06-24 — Community edition can't create templates via API

The self-hosted **Community (free)** edition gates programmatic
template-creation-from-a-file: `POST /templates/pdf` returns
`404 {"message":"This feature is available in Pro Edition"}`. Our
`DocuSealClient.create_signature_request` relies on exactly that call, so
the API-driven send paths (`POST /admin/signature-requests` and
`POST /admin/assemblies/{id}/signature-request`) only work on **Pro**.

Decision (no Pro purchase for now): keep the backend endpoints (they work
unchanged the moment a Pro licence is added), but the admin "Zur
Unterschrift senden" button no longer calls them. It hands the generated
protocol PDF into the **embedded DocuSeal UI** (Signaturen tab) instead:
download the PDF → upload it in DocuSeal → place the field → send.
UI-based template creation is free, and the signed PDF still returns via
the `form.completed` webhook. Revisit if one-click API sending is worth
the Pro tier.
