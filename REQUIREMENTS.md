# Wagner Hausverwaltung — Portal & App
## Requirements & Implementation Plan

This is the authoritative project spec for the WHV digital platform: an iOS app, a web portal, and the backend that powers both. The system is the digital frontend for property management work that is otherwise done in **Impower** (master data) and **SharePoint** (documents), and replaces ad-hoc email/phone communication with structured tickets, multi-channel messaging (Portal, WhatsApp, ePost), and AI-assisted self-service.

> **For Claude Code:** Treat this file as the source of truth. Each Phase is a self-contained milestone. Before implementing a module, read its full section, then propose a plan, then code. Prefer working software over abstract scaffolding — every phase must end in something deployable.

---

## 1. Project Overview

**Customer:** Wagner Hausverwaltung GmbH (WHV), Stuttgart
**Purpose:** Replace casavi-style portal functionality with an in-house platform optimized for WHV workflows, augmented with AI features that casavi/Impower do not offer.
**Users:**
- **Eigentümer** (WEG owners)
- **Mieter** (tenants under Mietverwaltung)
- **Beirat** (advisory board members, elevated owner role)
- **Dienstleister** (service providers / handworkers)
- **Verwalter** (WHV staff — currently just Luis, designed for team growth)

**Primary domains served:** `wagner-hausverwaltung.com` (marketing, Bluehost), `portal.wagner-hausverwaltung.com` (web portal), `api.wagner-hausverwaltung.com` (backend), `ai.wagner-hausverwaltung.com` (RAG service).

---

## 2. Goals & Non-Goals

### Goals
- Single source of truth for tenant/owner-facing communication and self-service
- Reduce phone/email volume to the Verwalter office by ≥60% within 12 months
- Digitize Umlaufbeschluss, ETV preparation, and document distribution end-to-end
- Provide AI-driven self-service that scales WHV without scaling headcount
- Be DSGVO- and BFSG-compliant from day one

### Non-Goals
- Not replacing Impower (Impower remains the accounting/master-data system of record)
- Not replacing SharePoint in v1 (SharePoint remains the document store; later: migration consideration)
- No payment processing in v1 (Impower handles SEPA/EBICS)
- No agentic actions on behalf of users without explicit confirmation

---

## 3. Architecture

```
┌──────────────┐    ┌──────────────────┐
│  iOS (Swift) │    │  Web (React+TS)  │
└──────┬───────┘    └────────┬─────────┘
       └──────────┬──────────┘
                  ▼
   api.wagner-hausverwaltung.com
     (FastAPI · Postgres · Redis · S3)
                  │
   ┌──────────────┼───────────────┬─────────────┬─────────────┐
   ▼              ▼               ▼             ▼             ▼
Impower API   E-POSTBUSINESS    WhatsApp     SharePoint    ai.wagner-
(REST +       (Deutsche Post    Cloud API    (Graph API)   hausverwaltung
 webhooks)     hybrid letters)  via 360dialog              .com (RAG)
```

**Principles:**
- Backend is the **only** thing that talks to Impower (rate limit 100/60s makes direct-client access impossible)
- Backend mirrors Impower master data in Postgres for read performance and offline-tolerance
- All write operations on master data go *through* the backend → Impower (never both ways at once for the same field)
- Clients (iOS, Web) talk only to `api.wagner-hausverwaltung.com`
- RAG runs as a separate service; the main backend enforces ACLs before forwarding queries

---

## 4. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Luis's primary language; async-native; great OpenAPI generation |
| ORM | **SQLAlchemy 2.0 + Alembic** | Mature, async support |
| Database | **PostgreSQL 16** | JSONB for flexible schemas, pgvector for embeddings |
| Cache/Queue | **Redis 7** | Rate-limit state, session, Celery broker |
| Workers | **Celery + Redis** | Impower sync, webhook fan-out, ePost polling |
| Object storage | **Hetzner Object Storage (S3-compatible)** or **Backblaze B2** | EU-hosted, DSGVO-friendly, cheap |
| iOS | **SwiftUI · iOS 17+ · Swift 5.10** | Native, modern, async/await |
| iOS storage | **SwiftData** | Modern Core Data successor for offline cache |
| Web | **React 18 + TypeScript + Vite + Tailwind + shadcn/ui** | Fast dev, good component primitives |
| Hosting | **Hetzner Cloud (Nürnberg)** for backend; Bluehost for static `portal.` | EU jurisdiction; cost-efficient |
| Container | **Docker Compose** (v1), Kubernetes later only if multi-tenant |
| CI/CD | **GitHub Actions** | Lint, test, build, deploy |
| Monitoring | **Sentry** + **Grafana/Loki/Prometheus** | Errors, logs, metrics |
| Auth | **JWT (access+refresh)** + **Sign in with Apple** + **WebAuthn/Passkeys** | Modern, mobile-friendly |
| Email | **Postmark** or **Resend** | Transactional, EU servers if possible |

---

## 5. Repository Structure

Monorepo, three top-level packages:

```
hausverwaltung/
├── REQUIREMENTS.md             # this file
├── CLAUDE.md                   # short pointer to REQUIREMENTS.md + conventions
├── README.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── backend/                    # FastAPI service
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── auth/
│   │   ├── api/v1/             # versioned REST endpoints
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/           # business logic per domain
│   │   ├── integrations/
│   │   │   ├── impower/
│   │   │   ├── epost/
│   │   │   ├── whatsapp/
│   │   │   ├── sharepoint/
│   │   │   └── email/
│   │   ├── workers/            # Celery tasks
│   │   └── tests/
│   └── Dockerfile
├── ios/                        # Xcode project
│   └── WagnerHausverwaltung/
│       ├── App/
│       ├── Features/
│       │   ├── Auth/
│       │   ├── Properties/
│       │   ├── Documents/
│       │   ├── Tickets/
│       │   ├── Messages/
│       │   └── Settings/
│       ├── Core/
│       │   ├── Networking/
│       │   ├── Persistence/
│       │   ├── Auth/
│       │   └── DesignSystem/
│       └── Tests/
├── web/                        # React portal
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── routes/
│       ├── features/
│       ├── components/
│       ├── lib/
│       └── styles/
├── rag/                        # RAG microservice
│   ├── pyproject.toml
│   └── app/
└── infra/
    ├── terraform/              # Hetzner provisioning (optional)
    ├── ansible/                # server config (optional)
    └── docs/                   # ADRs, runbooks
```

**Conventions:**
- All names in English in code; German preserved only for domain terms (Eigentümer, WEG, Hausgeld, Sondereigentum)
- API responses use snake_case JSON
- All times stored as UTC, displayed in user's timezone (default Europe/Berlin)
- Money stored as integer cents (`amount_cents` + `currency`)
- Soft-deletes via `deleted_at` for everything user-facing; hard-delete only via DSGVO request

---

## 6. Cross-Cutting Concerns

### 6.1 Authentication & Authorization
- JWT access token (15min) + refresh token (30 days, rotating, stored httpOnly cookie for web, Keychain for iOS)
- Sign in with Apple required when iOS app is published (Apple guideline)
- Passkey/WebAuthn for web (optional but recommended)
- Invite-code flow (see §7.3) is the **only** way to create accounts in v1 — no public signup
- 2FA optional via TOTP, required for Verwalter and Beirat roles
- Role model: `verwalter`, `beirat`, `eigentuemer`, `mieter`, `dienstleister`
- Authorization: row-level, scoped by `contact_id` → properties/units the user is associated with in Impower

### 6.2 DSGVO Compliance
- Verarbeitungsverzeichnis maintained in `/infra/docs/dsgvo/vvt.md`
- AVV templates for every sub-processor (Impower, Deutsche Post, 360dialog/Meta, Hetzner, Postmark)
- User-facing: in-app data export (JSON download of all personal data), account deletion in-app (Apple requirement)
- Audit log table: who accessed what when (all reads of Mieter/Eigentümer data by Verwalter logged)
- Data minimization: never copy more from Impower than needed for the active feature

### 6.3 Accessibility (BFSG, in force since June 2025)
- iOS: Dynamic Type support, VoiceOver labels on all interactive elements, 4.5:1 contrast minimum, no color-only signaling
- Web: WCAG 2.2 AA, semantic HTML, keyboard navigation, focus indicators, screen-reader testing in CI
- All forms have labels, error messages are descriptive and announced

### 6.4 Internationalization
- v1 ships **DE** and **EN**
- v1.1 adds **TR** and **RU** (high prevalence in urban Stuttgart rentals)
- All user-facing strings via `i18n` library; no hardcoded German in code

### 6.5 Observability
- Structured logging (JSON, with `request_id`, `user_id`, `contact_id`)
- Sentry for exceptions (frontend + backend)
- Health endpoint `/healthz` + `/readyz`
- Metrics: API latency p50/p95/p99, error rate, queue depth, Impower sync lag

### 6.6 Security
- All traffic HTTPS only (Let's Encrypt via Caddy/Traefik)
- HSTS, CSP, secure cookies
- Secrets in `.env` (dev) or sealed-secrets / Vault (prod), never in repo
- Pen-test before public launch
- Dependabot / Renovate for dependency updates
- Rate limiting per IP and per user on all endpoints

### 6.7 Automated health checks & self-remediation (Claude routine)

A scheduled Claude Code routine (configured via the `/schedule` skill) runs at a regular cadence — initial target **every 30 min** — and:

1. **Probes each integrated system with a lightweight read** (no writes, idempotent, low-impact). Per-system probes evolve as integrations come online:
   - **Backend**: `GET /healthz`, `GET /readyz` → 200 expected; `/readyz` body must report `postgres: true, redis: true`.
   - **Impower API**: `GET /v2/properties?size=1` with the configured bearer token → 200 expected; warn on 401 (token expired/rotated), 429 (rate-limited), 5xx (Impower outage).
   - **Object storage** (when added): list one bucket prefix.
   - **ePost** (Phase 4): account/credit balance endpoint.
   - **WhatsApp BSP** (Phase 4): number status / template status.
   - **SharePoint Graph** (Phase 5): drive listing.
   - **Email provider** (Phase 1.3b+): account API ping.

2. **Records each probe** with HTTP status, latency, and a body excerpt on failure. The routine writes a single status report per run.

3. **Addresses failures at three escalation levels**, in order:
   - **Auto-remediate** safe, idempotent fixes (e.g., `docker compose restart backend` when `/readyz` is 503 and the container is `unhealthy`; renew Let's Encrypt cert if Caddy hasn't done so).
   - **Diagnose-and-document** — capture container logs, recent commits, and the failing probe into a Markdown note under `infra/incidents/YYYY-MM-DD.md` for Luis to review.
   - **Escalate immediately** for user-facing failures (auth broken, sync stale > 24 h, certificate expired, data loss suspected) — notification channel TBD (push, email, or Slack); fallback is a high-priority incident note plus a flagged commit.

4. **Never mutates business data.** The routine reads, restarts infra containers, edits its own diagnostic notes — nothing else. Database/file mutations are explicitly out of scope.

5. **Versioned with the repo** — probe definitions and the schedule prompt live in `infra/scripts/health-checks/` so changes are reviewed.

First version lands alongside the Phase 1.7 staging deploy (so we're monitoring something real). Probe coverage grows with each new integration.

---

## 7. Phase 1 — Backend Foundation (4–6 weeks)

**Goal:** Functioning backend with Impower sync, auth, invite codes, and a minimal admin UI. No iOS/web yet.

### Phase 1 status snapshot (as of 2026-05-24)

| Sub-phase | Status | Notes |
|---|---|---|
| 1.1 Project bootstrap | ✅ shipped | uv · FastAPI · CI · docker-compose |
| 1.2 Database — core tables | ✅ shipped | 13 tables; enums match Impower; UUIDv7 PKs; see ADR-0002 |
| 1.3a Auth core | ✅ shipped | invite/redeem, login, refresh, logout, `/me`, `/me/properties` (incl. property detail with units) |
| 1.3b Auth finishers | ⏳ partial | `DELETE /me`, `/me/export`, forgot/reset-password all ✅ shipped 2026-05-24. Apple SIWA still pending (waiting on DUNS / Apple Developer enrollment). |
| 1.4a Impower client + sync | ✅ shipped | Hybrid codegen per ADR-0003; CLI sync verified: 24/129/361/179 rows |
| 1.4b Scheduled sync (Celery beat) | ✅ shipped | `worker` + `beat` containers; `sync_all_impower` task at 02:00 UTC daily. Verified end-to-end (30.87s for the full graph). |
| 1.4c Webhooks | ⏳ pending | not started |
| 1.4d Documents sync | ✅ shipped (iter 1: metadata) | 3,309 docs synced on staging; per-property iteration (Impower /v2/documents requires propertyId filter). File upload to Hetzner Object Storage stays as iter 2. |
| 1.5 Invite admin + email | ✅ shipped | `/admin/invites` POST/GET/DELETE wired with `require_role(VERWALTER)`; emails sent via Resend (ADR-0004), best-effort with audit trail; verified live end-to-end. |
| 1.6 Admin UI | ✅ shipped | Jinja2 + Pico.css at `https://admin.wagner-hausverwaltung.com/` (separate Caddy host → `/admin-ui/`). Cookie-session auth (HttpOnly/Secure/SameSite=Strict, 15-min TTL), VERWALTER-only. Dashboard counts, invites CRUD (create + send email + revoke + status filter), audit log view. 15 admin-UI tests in addition to the 7 admin-API tests; full suite at 85. |
| 1.7 Staging deploy | ✅ shipped | https://staging.api.wagner-hausverwaltung.com live; runbook at `infra/docs/staging.md` |
| 1.7+ Deploy hardening | ✅ shipped | Postgres backups (local + B2 off-site) ✅. Bruno collection ✅. CI/CD via GH Actions → GHCR → SSH ✅ (live 2026-05-24; pushes to main auto-deploy to staging). |
| §6.7 Health-check routine | ⏳ requirement added (this session), not implemented |

### 7.1 Project bootstrap — ✅
- [x] FastAPI project skeleton with config via Pydantic Settings
- [x] Postgres + Redis via docker-compose
- [x] Alembic migrations setup
- [x] CI pipeline: lint (ruff), type-check (mypy), test (pytest), build Docker image
- [x] `/healthz` and `/readyz` endpoints

### 7.2 Database — core tables — ✅
Initial migration `0001_initial_schema` ships 13 tables. Final shapes (after refinement against the live Impower spec) diverge from the sketch below in three ways: contracts↔contacts is m:n via `contract_contacts`; contacts split person/company via explicit `kind` enum; `voting_share` (MEA) added to units for Phase 4 Umlaufbeschluss. See [`backend/app/models/`](backend/app/models/) and [`backend/alembic/versions/`](backend/alembic/versions/) for the authoritative shape; ADR-0002 for tenancy rationale.

```sql
-- Identity (no Impower mirror)
organizations (id, name, ...)
users (id, organization_id, email, password_hash, sign_in_with_apple_sub, role,
       contact_id_impower, created_at, updated_at, deleted_at, last_login_at,
       mfa_secret, locale)
sessions (id, user_id, refresh_token_hash, expires_at, user_agent, ip_hash,
          last_used_at, revoked_at)
invite_codes (code, organization_id, email, contact_id_impower, role, scope_json,
              expires_at, consumed_at, created_by, created_at)
audit_log (id, organization_id, actor_user_id, action, target_type, target_id,
           payload_json, created_at)

-- Mirror of Impower master data (all rows: impower_id UNIQUE, raw_jsonb, last_synced_at)
properties (id, organization_id, impower_id, property_hr_id, name, type, state,
            city, street, number, postal_code, country, ...)
buildings (id, organization_id, property_id, impower_id, name, address, ...)
units (id, organization_id, impower_id, property_id, building_id, unit_hr_id, type,
       floor, position, unit_rank, is_owned_by_weg, voting_share, area_m2, rooms)
contracts (id, organization_id, impower_id, property_id, unit_id, type, contract_number,
           name, start_date, end_date, is_vacant, ...)
contract_contacts (contract_id, contact_id, role, created_at)  -- m:n junction
contacts (id, organization_id, impower_id, kind, salutation, title, first_name,
          last_name, company_name, vat_id, trade_register_number, email, phone,
          additional_contacts, city, street, ..., preferred_channel, ...)
contact_bank_accounts (id, contact_id, iban, bic, account_holder_name, ...)

-- Documents (metadata mirror; files live in SharePoint or S3)
documents (id, organization_id, impower_id, sharepoint_id, property_id, building_id,
           unit_id, contract_id, contact_id, name, kind, impower_source_type,
           mime_type, size_bytes, storage_url, amount, issued_date, visibility, state, ...)
```

### 7.3 Auth module — ⏳ partial
- [x] `POST /auth/invite/redeem` — exchanges invite code + email for first password setup
- [x] `POST /auth/login` (email + password) → access + refresh
- [x] `POST /auth/refresh`
- [x] `POST /auth/logout`
- [ ] `POST /auth/apple` (Sign in with Apple ID token verification) — depends on Apple Developer Program (DUNS in flight)
- [x] `POST /auth/forgot-password` — always 204 (no enumeration); on hit, single-use sha256-hashed token persisted in `password_reset_tokens`, raw token emailed via Resend (German template); 30-min TTL
- [x] `POST /auth/reset-password` — validates token; updates `password_hash`; **revokes every active session for the user**; marks token consumed; writes `audit_log` row
- [x] `GET /me` (current user + scope)
- [x] `GET /me/properties` (scoped: VERWALTER sees all; EIGENTUEMER scoped via contact_id_impower → contracts → properties)
- [x] `GET /me/properties/{id}` (property detail with embedded units, scope-checked, 404 on out-of-scope)
- [x] `DELETE /me` — soft-delete (`users.deleted_at`), revokes all the user's active sessions, writes an `audit_log` row (`user_self_delete`). Hard-delete after 30 days is a future operational job.
- [x] `GET /me/export` — DSGVO Art. 20 JSON: user profile (no `password_hash`/`mfa_secret`), sessions metadata (no `refresh_token_hash`), audit entries where actor=self; `Content-Disposition: attachment` for browser download.

### 7.4 Impower integration — ⏳ partial
- [x] Pydantic DTOs generated from spec; client handwritten — see ADR-0003 (deviation from "full generated client")
- [x] `integrations/impower/client.py` — async httpx, Bearer auth, retry on 5xx + ConnectError, 429 Retry-After
- [x] Pagination iterators for properties, units, contracts, contacts
- [x] Manual sync via CLI: `python -m app.integrations.impower sync [entity|all]` — upserts via `INSERT … ON CONFLICT (impower_id)`; populates `contract_contacts` junction
- [x] **1.4b** — Celery `worker` + `beat` containers; `sync_all_impower` task runs at 02:00 UTC daily (one hour before the postgres backup). Full sync of properties → units → contacts → contracts → documents. Verified live: 30.87s for the entire graph. Delta sync (`updated_since`) deferred — Impower's v2 spec doesn't expose it on most endpoints; webhooks handle real-time updates between nightly runs.
- [ ] **1.4c** — Webhook endpoint `/webhooks/impower` — register connection via Impower `POST /v2/connections` with `appId=8`; verify signature; idempotent processing keyed on `(entityType, entityId, eventType)`
- [x] **1.4d (iter 1)** — Documents metadata mirror — per-property iteration (Impower's `/v2/documents` requires `propertyId` filter, unfiltered times out); 31-value `sourceType` enum mapped to our 8-value `DocumentKind` with `SONSTIGES` catchall + raw `impower_source_type` retained
- [ ] **1.4d (iter 2)** — File body upload to Hetzner Object Storage (D8)
- [ ] Reconciliation job: detect drift between mirror and Impower, alert on Sentry

### 7.5 Invite-code flow — ⏳ partial
- [x] Bootstrap CLI: `python -m app.auth.bootstrap create-invite <email> --role <...>` (chicken-and-egg solver for the first Verwalter, since `/admin/invites` would require auth)
- [x] Code: 8 chars, alphanumeric (no `0`/`O`/`1`/`I`/`L`), single-use, 14-day TTL
- [x] After redemption, user is bound to the Impower `contact_id_impower` and inherits read scope
- [x] Admin-only endpoint: `POST /admin/invites { email, role, contact_id_impower?, scope_json?, ttl_days }` — protected by `require_role(VERWALTER)`; creates invite + sends Resend email + writes audit row in one commit
- [x] `GET /admin/invites?status=pending|consumed|expired` and `DELETE /admin/invites/{code}` (revoke pending)
- [ ] Bulk invite via CSV upload — not started, low priority
- [x] Email via **Resend** (ADR-0004) — best-effort send: failure logs to audit + leaves invite redeemable; iOS deep link (`whv://invite/CODE`) + web fallback URL pending the actual web/iOS clients

### 7.6 Minimal admin UI — ✅ shipped
Server-rendered Jinja2 + Pico.css (D10 → Jinja2). Mounted at `/admin-ui/*` on the backend; Caddy publishes it at `https://admin.wagner-hausverwaltung.com/` (with `/` rewritten to `/admin-ui/`). Single host avoids a second TLS cert + CORS hop. Auth via HttpOnly cookie (`whv_admin_session`, SameSite=Strict, Secure outside dev), VERWALTER-only — non-Verwalter login returns 401, unauthenticated requests redirect to `/admin-ui/login` via `NeedsLoginRedirect` exception handler.

- [x] Dashboard with org-scoped counts (open / consumed invites, properties, units, contracts, contacts)
- [x] Invite create (German form: email + role + optional Impower-Contact-ID + TTL) — wires the same code path as `POST /admin/invites`: row + Resend email + audit log in one commit
- [x] Invites list with `pending` / `consumed` / `expired` filter (latest 200)
- [x] Revoke pending invite (POST form with JS confirm)
- [x] Audit-log view with collapsible JSON payloads (latest 200, org-scoped)
- [ ] Contact search across the synced mirror — not in iter 1; iOS/web portals will surface this when they exist

### 7.7 Definition of Done (Phase 1)
- [x] Backend deployed to staging on Hetzner Cloud — https://staging.api.wagner-hausverwaltung.com
- [x] Bruno collection committed in `backend/api-tests/` (chose Bruno over Postman — plain text, git-diffable, no cloud account)
- [x] Luis can invite his own personal Impower contact, redeem the invite, log in, see his properties
- [x] All endpoints documented in OpenAPI / Swagger UI at `/docs`
- [x] Test coverage ≥ 70% on services and integrations (85 tests covering models, sync, client, auth, /me, webhooks, workers, admin invites, admin UI — all green)

---

## 8. Phase 2 — iOS App MVP (4–6 weeks)

**Goal:** Shippable iOS app with the core casavi-equivalent feature set.

### 8.1 Xcode project setup
- [ ] Xcode 15+, iOS 17+ deployment target
- [ ] Bundle identifier: `de.wagner-hausverwaltung.app`
- [ ] SwiftUI app lifecycle, SwiftData for persistence
- [ ] Tuist or XcodeGen for reproducible project generation (optional but recommended)
- [ ] App Store Connect entry created with placeholder metadata
- [ ] D-U-N-S number obtained for Wagner Hausverwaltung GmbH (do this FIRST — 1-2 weeks lead time)

### 8.2 Architecture
- MVVM with a `Repository` layer abstracting "remote + local"
- `APIClient` actor with async/await, automatic token refresh, exponential backoff
- `AuthStore` ObservableObject as single source of auth truth
- SwiftData models mirror backend schemas for offline cache

### 8.3 Screens (v1)
- [ ] **Onboarding/Invite**: enter email + invite code OR Sign in with Apple
- [ ] **Login** (returning users)
- [ ] **Property list** (if user has multiple properties/units)
- [ ] **Property detail**: address, type, contact card for Verwalter, quick actions
- [ ] **Documents**: list filtered by Jahresabrechnung / Protokoll / Vertrag / Sonstiges, with search and download
- [ ] **Tickets list**: open / closed, with status badges
- [ ] **Ticket detail**: thread of comments, photo attachments, status timeline
- [ ] **New ticket**: photo (camera or library), title, category, description, optional location
- [ ] **Messages**: inbox of announcements / notifications
- [ ] **Settings**: profile, language, notification preferences, biometrics, **delete account** (Apple requirement), support contact, privacy policy link
- [ ] **About**: version, legal notices, third-party licenses

### 8.4 Cross-screen requirements
- [ ] Pull-to-refresh on all lists
- [ ] Empty states with helpful copy
- [ ] Skeleton loaders, not spinners
- [ ] Offline banner when not connected; cached data still readable
- [ ] Push notifications via APNs (request permission only on contextual screen, never on first launch)
- [ ] Deep links: `whv://invite/CODE`, `whv://ticket/123`, `whv://document/456`
- [ ] Biometric lock (Face ID / Touch ID) on app foreground, configurable

### 8.5 Design system
- [ ] Color palette: WHV brand colors + semantic tokens (success, warning, danger, info)
- [ ] SF Symbols throughout
- [ ] Typography: SF Pro, scaled with Dynamic Type
- [ ] Components: Card, ListRow, StatusBadge, EmptyState, ErrorState, FormField

### 8.6 Pre-submission checklist
- [ ] App icon (1024×1024 + all sizes)
- [ ] Screenshots: 6.9", 6.5", 5.5" iPhone (iPad optional in v1)
- [ ] App Store description (DE + EN)
- [ ] Keywords (DE + EN)
- [ ] Privacy policy URL (public, on `wagner-hausverwaltung.com/datenschutz-app`)
- [ ] App Privacy nutrition labels filled in App Store Connect
- [ ] Demo account for App Review with seeded data
- [ ] Review notes explaining the invite-only model

### 8.7 Definition of Done (Phase 2)
- App submitted to TestFlight, 10–20 external beta testers (real WHV owners/tenants)
- Crash-free sessions ≥ 99.5% in TestFlight
- App approved by Apple and live on the App Store (unlisted or public — Luis's choice)

---

## 9. Phase 3 — Web Portal MVP (2–3 weeks)

**Goal:** Browser-based equivalent of iOS app for users who prefer desktop or non-iOS devices.

### 9.1 Setup
- [ ] Vite + React + TS + Tailwind + shadcn/ui
- [ ] React Router v6+
- [ ] TanStack Query for data fetching
- [ ] Zustand for client state
- [ ] Static build deployable to Bluehost (`portal.wagner-hausverwaltung.com`) **or** served from the same Hetzner box behind Caddy

### 9.2 Pages
Mirror iOS feature set:
- [ ] Login / invite redemption
- [ ] Dashboard
- [ ] Property list & detail
- [ ] Documents
- [ ] Tickets
- [ ] Messages
- [ ] Settings (incl. account deletion, data export)

### 9.3 Responsive
- Mobile-first, but desktop-optimized layouts at md+ breakpoints
- Print-friendly stylesheet for documents

### 9.4 Definition of Done (Phase 3)
- Deployed at `portal.wagner-hausverwaltung.com`
- Lighthouse: Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95
- Works in Safari, Chrome, Firefox, Edge (last 2 versions)

---

## 10. Phase 4 — Communication & Workflow (6–10 weeks)

### 10.1 E-POSTBUSINESS API integration
**Module:** `backend/app/integrations/epost/`

WHV already has the API contract. Build:
- [ ] `client.py` — auth (login → token), token caching in Redis, retry, rate-limit
- [ ] `service.py` — `send_letter()`, `get_status()`, `bulk_send()`, `cancel()`
- [ ] `models.py` — LetterRequest, LetterOptions (color, duplex, einschreiben, gogreen)
- [ ] PDF rendering pipeline: Jinja2 HTML template → WeasyPrint → PDF
- [ ] DIN-conform address position (Fensterumschlag, ~25mm from top-left)
- [ ] Status polling worker: every 4 hours
- [ ] Auto-archive sent letter as Impower document on the contact
- [ ] Templates:
  - Mahnung Hausgeld
  - ETV-Einladung
  - Umlaufbeschluss-Versand
  - Jahresabrechnung-Versand (Einschreiben option)
  - Mieterhöhung §558 BGB
  - Generic custom-text letter

**`letters` table:**
```sql
letters (id, contact_id, property_id, template_id, rendered_pdf_url,
         epost_shipment_id, status, status_history jsonb,
         options jsonb, cost_cents, page_count,
         created_by, created_at, sent_at, delivered_at)
```

⚠️ **Single-software lock:** E-POSTBUSINESS API may only be active in one software. If currently active in Impower, must be deactivated there before WHV backend goes live.

### 10.2 WhatsApp Business Cloud API integration
**Module:** `backend/app/integrations/whatsapp/`

Via 360dialog (Berlin BSP, DSGVO-friendly) — the official WhatsApp Business app on the phone must be deregistered first or a separate number used.

- [ ] Webhook receiver `/webhooks/whatsapp` — verify signature, route by phone number → contact
- [ ] Inbound message → comment on existing ticket OR new ticket
- [ ] Outbound: free text within 24h service window; pre-approved templates outside
- [ ] Pre-approve templates with Meta in DE:
  - `ticket_status_update`
  - `mahnung_hinweis`
  - `etv_einladung_hinweis`
  - `beschluss_hinweis`
- [ ] Media handling: photos in WA → attached to ticket
- [ ] DSGVO: AVV with 360dialog + Meta, processing record updated

### 10.3 Multi-channel notification orchestration
Add `preferred_channel` enum to users: `portal | email | whatsapp | epost`, with fallback chain.

Notification dispatcher service:
```python
def notify(user, event):
    if user.has_portal_account and channel_supports(event, "portal"):
        send_push_and_inbox(user, event)
    elif user.whatsapp_opt_in and within_window:
        send_whatsapp(user, event)
    elif user.email:
        send_email(user, event)
    else:
        queue_epost(user, event)
```

### 10.4 Tickets v2 (unified inbox)
- [ ] Verwalter sees one thread per ticket combining portal messages + email replies + WhatsApp + phone-note (manual entry)
- [ ] Internal notes (visible only to Verwalter)
- [ ] Assign-to (when WHV grows beyond Luis)
- [ ] SLA timers with auto-escalation
- [ ] Category taxonomy: Schaden, Verwaltung, Hausgeld, Sonstiges, with sub-categories

### 10.5 Umlaufbeschluss module
Per WEMoG (§23 Abs. 3 WEG), support both modes:
- Classic (Allstimmigkeit in Textform)
- Mehrheits-Umlaufbeschluss (requires prior ETV majority enabling it)

```sql
circular_resolutions (id, property_id, title, description, mode, status,
                      pdf_url, opens_at, closes_at, required_quorum,
                      created_by, created_at, decided_at, result, result_pdf_url)
circular_votes (id, resolution_id, owner_contact_id, choice,
                voted_at, ip_hash, signature_method, evidence_jsonb)
```

- [ ] Verwalter creates resolution (rich text editor + optional PDF attachment)
- [ ] Dispatcher routes invitation per `preferred_channel` (incl. ePost for offline owners)
- [ ] Owner votes in portal/app: clickable Ja/Nein/Enthaltung + confirmation email
- [ ] Live quorum view for Verwalter
- [ ] At `closes_at`, auto-tally, generate final PDF with vote log, upload to Impower

### 10.6 ETV digital (hybrid sessions, post-WEMoG)
- [ ] Agenda builder with TOPs
- [ ] Digital invitations with calendar `.ics` attachment
- [ ] Vollmacht (proxy) digital
- [ ] During session: live voting via app, Verwalter dashboard with results
- [ ] Auto-generated minutes draft from votes

### 10.7 Belegeinsicht
- [ ] Pre-ETV: owners can browse all invoices of the Jahresabrechnung in the portal (huge time-saver vs. in-person inspection)
- [ ] Documents pulled from Impower or SharePoint, ACL-checked, watermarked with viewer name + timestamp

### 10.8 Announcements / Mitteilungen — ✅ shipped 2026-05-25

Property-scoped messages from Verwalter to Eigentümer / Mieter / Beirat, with an editorial delay before fan-out, attachments, and an in-portal comment thread with admin moderation. The closest analog is a tenant-association bulletin board: many-to-some, low-volume, often time-sensitive ("Wasser fällt morgen 9–11 Uhr aus"), occasionally with a PDF protocol attached.

**Data model** (`announcements` + `announcement_attachments` + `announcement_comments`):

- Audience: three booleans (`audience_eigentuemer`, `audience_mieter`, `audience_beirat`) with a CHECK constraint that at least one is true. Audience is applied **at read time** so post-publish edits take effect immediately on the portal — no audience snapshot.
- Lifecycle: create → `scheduled_publish_at = now() + 10 min` → each PATCH while unpublished resets the timer (editorial buffer) → fan-out → `notification_sent_at` stamped → row drops out of the publish-due partial index.
- Post-publish edits are allowed; the portal shows a "bearbeitet am DD.MM." indicator when `updated_at` exceeds `notification_sent_at + 60s`.
- Soft-delete via `deleted_at`. Pre-publish deletes also prevent fan-out. Comments are not soft-deleted with the parent but become invisible by virtue of the parent being hidden.

**Comment moderation**: hide-only, reversible. `is_hidden = true` filters the comment out of all non-admin reads; `hidden_at` / `hidden_by_user_id` / `hidden_reason` provide an audit trail. No hard-delete in v1.

**Fan-out**: Celery beat task `publish_due_announcements` runs every minute. Hits a partial index `WHERE notification_sent_at IS NULL AND deleted_at IS NULL`, so the scan stays O(due-rows) regardless of historical volume. Per-recipient send (no BCC leak); `notification_sent_at` stamped *before* the send loop to make retries idempotent. Email body = subject + body + attachment list + portal deep link, sent via Resend with binary attachments base64-encoded.

**API surface** (full list in `app/api/v1/announcements.py`):

- Admin: `POST/GET /admin/properties/{pid}/announcements`, `GET/PATCH/DELETE /admin/announcements/{id}`, `POST /admin/announcements/{id}/publish-now`, attachment + comment-moderation endpoints.
- Owner: `GET /me/properties/{pid}/announcements`, `GET /me/announcements/{id}`, attachment downloads, `POST /me/announcements/{id}/comments`.

**UI**:

- Admin: a "Mitteilungen" tab on the property detail page (alongside Übersicht / Tickets / Dokumente / Firmen); compose lives in a modal on the list; `/admin/announcements/:id` is the single-screen detail with edit + publish-now + delete + attachments + comments + per-comment hide/unhide.
- Portal: an entry button on the property detail page → `/properties/:id/announcements` list → `/announcements/:id` detail with attachments + comment thread + compose box.

**Design choices** (full rationale in ADR-0006): audience as 3 booleans (not a join table); 10-min editorial delay with timer-reset-on-edit (each save extends the buffer); body as plain text (not Markdown — no XSS surface); hide-only moderation (reversible); 1-min Celery cadence.

**Tests**: 19 backend tests in `app/tests/test_announcements.py` covering lifecycle, scope, audience filter, attachments, moderation, and fan-out idempotency.

### 10.9 Definition of Done (Phase 4)
- All four channels (portal, email, WhatsApp, ePost) live and routed via dispatcher
- At least one Umlaufbeschluss successfully run end-to-end with a real WEG
- One ETV held in hybrid mode

---

## 11. Phase 5 — AI Layer (8–12 weeks, parallelizable with Phase 4)

**Goal:** Make WHV the only Hausverwaltung in the segment with first-class AI features.

### 11.1 RAG service
**Separate service:** `rag/` → deployed as `ai.wagner-hausverwaltung.com`
- [ ] Document ingestion from SharePoint via Microsoft Graph API (webhooks on Drive)
- [ ] Parsing pipeline: Apache Tika / Unstructured.io / Docling (Luis to evaluate)
- [ ] Structured chunking (TOP-wise for protocols, position-wise for Jahresabrechnungen)
- [ ] Embeddings: `multilingual-e5-large` (Luis already familiar)
- [ ] Vector store: pgvector (same Postgres) or Qdrant (separate)
- [ ] **ACL-aware retrieval:** every chunk tagged with `tenant_id` (property), `unit_id`, `sensitivity`. Hard filter BEFORE vector search.
- [ ] Role-differentiated answers:
  - Verwalter → all
  - Eigentümer → their WEG + personal docs
  - Mieter → their contract + Hausordnung
- [ ] Query API: `POST /ai/ask` { question, conversation_id? } → streaming response with citations
- [ ] Evaluation harness: synthetic QA sets per property, regression tracking — Luis's PhD research applies directly

### 11.2 Verbrauchs-Anomaly-Detection
- [ ] Pull consumption data (Heizung, Wasser, Strom) from Impower / HKVO data
- [ ] Per-unit baseline + comparison to similar units (same property, similar Wohnfläche, similar Personenzahl)
- [ ] Statistical outlier detection (z-score or isolation forest)
- [ ] Proactive push: "Deine Heizkosten Q1 lagen 38% über Vergleichswohnungen — möglicher Hydraulikabgleich, Termin vereinbaren?"

### 11.3 Predictive maintenance
- [ ] Inventory of building systems (Heizung, Aufzug, Feuerlöscher, Trinkwasser, Rauchmelder) per property
- [ ] Wartungshistorie + Anlagenalter
- [ ] Failure-pattern model (Luis's PhD spare-parts work transfers structurally)
- [ ] Beirats-Cockpit: budget forecasts, IHR-Entnahmerate projections

### 11.4 Voice-Schadenmeldung
- [ ] On-device Whisper or server-side
- [ ] LLM classifies category, extracts location/details
- [ ] Auto-creates ticket draft, asks for photo confirmation

### 11.5 AR-Schadensaufnahme (iOS-only, optional)
- [ ] RoomPlan API (iPhone Pro)
- [ ] 3D room model + damage marker
- [ ] Handworker sees position in 3D when opening the ticket

### 11.6 Definition of Done (Phase 5)
- RAG answering ≥ 80% of common questions correctly (eval set required)
- Verbrauchs-Anomalien produce ≥ 1 actionable insight per property per year on average
- At least one predictive maintenance alert validated as accurate

---

## 12. Deployment

### 12.1 Environments
- **dev** — local via docker-compose
- **staging** — `staging.api.wagner-hausverwaltung.com` on Hetzner CX22 in Nürnberg
- **prod** — `api.wagner-hausverwaltung.com` on Hetzner CX32 (upgradeable)

### 12.2 Deployment process
- GitHub Actions on push to `main` → build Docker images → push to registry → SSH deploy
- Migrations run automatically before app start (with backup snapshot first)
- Blue-green or rolling restart via Docker Compose
- Manual approval gate for prod

### 12.3 Backups
- Postgres: daily full + WAL streaming to off-site (Backblaze B2)
- 30-day retention
- Quarterly restore drill

---

## 13. App Store Submission Checklist

Pre-requisites (do these first, in parallel with development):
- [ ] D-U-N-S number for WHV GmbH (1–2 weeks)
- [ ] Apple Developer Program enrollment as **Organization** (1–4 weeks Apple verification)
- [ ] Apple Developer agreements signed, banking + tax info filled in App Store Connect
- [ ] Privacy policy live on a public URL
- [ ] Terms of service / AGB live on a public URL
- [ ] Bundle ID registered, App Store Connect app entry created

Submission-time:
- [ ] App Privacy nutrition labels accurately filled
- [ ] Screenshots in all required sizes
- [ ] Description, keywords, support URL, marketing URL
- [ ] Demo account credentials in review notes
- [ ] Account deletion functional in-app
- [ ] Sign in with Apple if any other social login is offered
- [ ] No private API usage, no Enterprise distribution

---

## 14. Open Decisions

| # | Decision | Default if undecided | Status |
|---|---|---|---|
| D1 | Self-host vs. managed Postgres | Self-host on Hetzner | ✅ resolved 2026-05-24 — staging runs self-hosted postgres:16 on cax21 |
| D2 | pgvector vs. Qdrant | pgvector (one less service) | Open — needed for Phase 5 |
| D3 | Public vs. unlisted App Store | Public + invite-gating | Open — needed for Phase 2 submission |
| D4 | WhatsApp via 360dialog vs. Meta direct | 360dialog (faster onboarding) | Open — needed for Phase 4 |
| D5 | Single GmbH-app vs. multi-tenant SaaS | Single now, multi-tenant-ready schemas | ✅ resolved 2026-05-24 → ADR-0002 |
| D6 | Web portal hosted on Bluehost (static) vs. Hetzner | Hetzner — simpler ops | Open — needed for Phase 3 |
| D7 | RAG embedding model | `multilingual-e5-large` | Open — needed for Phase 5 |
| D8 | Object storage for documents | Hetzner Object Storage (EU, in ecosystem, S3-compatible) | ✅ resolved 2026-05-24 — Hetzner Object Storage. ADR to write on first use |
| D9 | Transactional email provider | Postmark or Resend (both EU-friendly) | ✅ resolved 2026-05-24 — **Resend** in eu-west-1 → ADR-0004; domain `wagner-hausverwaltung.com` verified |
| D10 | Admin UI framework | Jinja2 server-rendered (simplest, least new tech) | ✅ resolved 2026-05-24 — **Jinja2** server-rendered (HTMX added if/when interactivity needs it). ADR to write on first use |
| D11 | Impower client codegen approach | Hybrid: Pydantic DTOs generated, HTTP handwritten | ✅ resolved 2026-05-24 → ADR-0003 |
| D12 | CI/CD deploy mechanism for staging | GitHub Actions → GHCR → SSH `docker compose pull` | ✅ resolved 2026-05-24 — **GHCR push + SSH pull** (Actions builds & pushes to private GHCR, then SSHes to staging and runs `docker compose pull && up -d`). ADR to write on first use |

Document every decision as an ADR in `infra/docs/adr/NNNN-title.md` once made.

---

## 15. Phasing Summary

| Phase | Duration | Output |
|---|---|---|
| 1 | 4–6 wks | Backend live on staging, invite flow works |
| 2 | 4–6 wks | iOS app on TestFlight, then App Store |
| 3 | 2–3 wks | Web portal live |
| 4 | 6–10 wks | Multi-channel + Umlaufbeschluss + ETV digital |
| 5 | 8–12 wks | RAG, anomaly detection, predictive maintenance |

Phases 4 and 5 can run partially in parallel. Total to feature-complete: ~24–37 weeks of focused work, realistic for a side-project pace given Luis's PhD + WHV operations: budget 9–15 months.

### 15.1 Next iteration priorities (2026-05-24)

The remaining work in Phase 1, in recommended execution order. Sizes are S (≤1 session), M (1–3 sessions), L (3+ sessions).

| # | Work | Size | Blockers |
|---|---|---|---|
| 1 | **§6.7 health-check routine** — scheduled Claude routine probing `/healthz`, `/readyz`, Impower `GET /properties?size=1` every 30 min | S | none |
| 2 | **Phase 1.4d iter 2: documents file upload** — fetch document body from Impower, store in Hetzner Object Storage, populate `storage_url` + `mime_type` + `size_bytes`. Iter 1 metadata is live (2026-05-24). | M | none |
| 3 | ~~Phase 1.3b `DELETE /me` + `GET /me/export`~~ — ✅ shipped 2026-05-24 (54 tests green, live smoke OK) | S | done |
| 4 | ~~Phase 1.5 admin invites + Resend email~~ — ✅ shipped 2026-05-24 (ADR-0004, 63 tests green, live email send verified) | M | done |
| 5 | ~~Phase 1.7+ CI/CD via GHCR + SSH~~ — ✅ shipped 2026-05-24. Push to main → build linux/arm64 → push to GHCR (public) → SSH staging → pull + migrate + restart + curl /healthz. ~70s end-to-end. | M | done |
| 6 | ~~Phase 1.7+ Postgres backups to B2~~ — ✅ shipped 2026-05-24 (local + B2 off-site, 30-day retention both sides) | S | done |
| 7 | **Phase 1.3b auth finishers** — forgot/reset-pw ✅ shipped 2026-05-24. SIWA still pending DUNS / Apple Developer enrollment. | M | DUNS for SIWA only |
| 8 | **Phase 1.4c webhooks** — `POST /webhooks/impower` receiver + HMAC + Impower-side connection registration | S | none |
| 9 | ~~Phase 1.4b Celery beat~~ — ✅ shipped 2026-05-24 (worker + beat live, nightly 02:00 UTC) | M | done |
| 10 | ~~Phase 1.6 admin UI~~ — ✅ shipped 2026-05-24 (Jinja2 + Pico.css at admin.wagner-hausverwaltung.com, cookie auth, dashboard + invites CRUD + audit log; 15 new tests, 85 total green) | L | done |
| 11 | ~~Phase 1.7+ Postman/Bruno collection~~ — ✅ shipped 2026-05-24 (Bruno, `backend/api-tests/`) | S | done |
| 12 | **Phase 2 iOS scaffold** — Xcode project + first 2-3 screens hitting staging | L | DUNS before App Store submission; can scaffold without |
| 13 | **Phase 3 web portal MVP** — ⏳ in flight 2026-05-24. Pages 1-6: invite redeem, login, forgot/reset, property list, property detail, documents, settings. React 18 + TS + Vite + Tailwind. Lives at `portal.wagner-hausverwaltung.com`. Tokens in localStorage (XSS tradeoff acknowledged; iOS uses Keychain). | M | none — backend `/me/*` endpoints already wired + scope-tested |

All Phase 1 work is now unblocked (D8/D9/D10/D12 resolved 2026-05-24). Items 1–11 close Phase 1 fully (~4–6 weeks of focused work). A "minimum to start Phase 2" cut is items 1, 2 (iter 1), 3, 8, 11 (~1–2 weeks).

---

## 16. Conventions for Claude Code

When working on this repo:
1. **Read this file first**, then the relevant phase section, before writing any code.
2. **Propose a plan before implementing** anything non-trivial. Wait for confirmation.
3. **Write tests** alongside features. No untested business logic.
4. **Keep secrets out of the repo.** Use `.env.example` to document required env vars.
5. **Prefer composition over inheritance**, **explicit over implicit**, **boring tech over novel**.
6. **Always create a migration** when changing the schema. Never edit applied migrations.
7. **Document any deviation from this spec** in `infra/docs/adr/`.
8. **German legal terms stay German.** Never translate Eigentümer, WEG, Sondereigentum, Hausgeld, Umlaufbeschluss, etc.
9. **When in doubt about a feature scope, ask.** This document is the spec; surprises in scope creep are not welcome.
