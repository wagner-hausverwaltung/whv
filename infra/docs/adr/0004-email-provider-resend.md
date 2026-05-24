# ADR-0004: Email provider — Resend (eu-west-1)

- Date: 2026-05-24
- Status: Accepted
- Resolves: REQUIREMENTS.md §14 D9

## Context

REQUIREMENTS.md lists "Postmark or Resend (both EU-friendly)" as the candidates for transactional email. Email is needed for: invite delivery (Phase 1.5), forgot-password (Phase 1.3b), and future workflow notifications (Phase 4).

## Decision

Use **Resend** (https://resend.com), with the sending domain `wagner-hausverwaltung.com` verified in the **eu-west-1** (Frankfurt) region.

- The Resend account is owned by WHV (`wagner-hausverwaltung`); API keys are managed at https://resend.com/api-keys.
- The sending domain was verified 2026-05-08 with SPF, DKIM, and Return-Path DNS records on `wagner-hausverwaltung.com` (Bluehost DNS).
- Default From: `Wagner Hausverwaltung <noreply@wagner-hausverwaltung.com>`. Both the name and address are configurable via `EMAIL_FROM_NAME` / `EMAIL_FROM_ADDRESS` env vars.
- The HTTP client is hand-rolled `httpx.AsyncClient` (one per request, low volume; closed in the FastAPI dep teardown). Resend's official Python SDK is sync, and the REST surface we need is small enough that direct calls keep the code more readable and async-native.

### Send semantics

`POST /admin/invites` and similar endpoints follow a **best-effort send** pattern:
1. The invite row is persisted first.
2. The email send is attempted.
3. Whether it succeeds or fails, the invite is created and an audit-log row is written. The audit's `payload_json` records `email_sent` (bool), `email_message_id` (if any), and `email_error` (string, first 200 chars, if any).
4. A failed send is recoverable — the Verwalter can re-issue the invite or relay the code out-of-band.

This avoids the worst-case "invite was created but the customer doesn't know, and the admin doesn't either."

## Why Resend over Postmark

- **DX**: Modern REST API, single auth header, JSON in/out. Postmark is fine but feels older.
- **EU region (eu-west-1, Frankfurt)** for DSGVO posture — Postmark also has EU but Resend's UI is closer to a single-region pick.
- **Pricing**: free tier covers 3,000 emails/month — plenty for staging + early invite volume; both providers comparable beyond that.
- **Cleaner local-dev story**: `delivered@resend.dev` is a no-op test recipient that goes through the full pipeline without spamming any real inbox.

## Consequences

- We are coupled to Resend's REST API shape. Migrating to a different provider means rewriting `app/integrations/email/client.py` (~80 LOC) and any templates that use provider-specific markup (none today; plain HTML + text).
- The API key `RESEND_API_KEY` is a secret. Local: `.env` (gitignored). Staging: server `.env` (perms 600, generated/added directly on the server when rotating).
- Domain verification belongs to the wagner-hausverwaltung.com DNS zone at Bluehost. If we ever change the email provider OR add a second sending subdomain (e.g., `letters.wagner-hausverwaltung.com`), update the DNS there and revoke the old records.
- Forgot-password (Phase 1.3b) and future workflow notifications (Phase 4) reuse the same `EmailClient` and follow the same best-effort pattern.
