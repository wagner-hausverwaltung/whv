# CLAUDE.md

This is the Wagner Hausverwaltung GmbH (WHV) digital platform: backend, iOS app, web portal, and RAG service.

## Read first

**`REQUIREMENTS.md`** in the repo root is the authoritative spec. Read the relevant section before implementing anything. Do not proceed without context.

The §7 "Phase 1 status snapshot" and §15.1 "Next iteration priorities" tables show what's shipped vs. what's next — start there to orient.

## What's running (as of 2026-05-24)

- **Staging API**: https://staging.api.wagner-hausverwaltung.com — Hetzner cax21 in Nürnberg, Caddy + Let's Encrypt, full demo loop works (invite → redeem → login → `/me/properties/{id}` with units). Op runbook: [`infra/docs/staging.md`](infra/docs/staging.md).
- **Admin UI**: https://admin.wagner-hausverwaltung.com — Jinja2 + Pico.css; cookie-session auth, VERWALTER-only; dashboard + invites CRUD + audit log. Caddy rewrites `/` → `/admin-ui/` and reverse-proxies to the same backend container. Today this host points at staging; when prod ships, the DNS record moves to prod and a `staging.admin.*` is added for staging.
- **Web Portal**: https://portal.wagner-hausverwaltung.com — React 18 + TS + Vite + Tailwind SPA for Eigentümer / Mieter / Beirat. Static bundle served by an nginx container, behind Caddy. Calls the API cross-origin via JWT in `Authorization` header (backend CORS allowlist gates this). DNS prerequisite: A record → 46.225.185.151.
- **Local dev**: `docker compose up` brings up postgres + redis + backend + web. Web hot-reload via `cd web && npm run dev` (Vite proxy on :5173 forwards `/api` to backend on :8000). `.env` (gitignored) has the Impower test-instance token.
- **Resolved infrastructure picks** (D8/D9/D10/D12, all 2026-05-24): Hetzner Object Storage for documents · Resend for transactional email · Jinja2 server-rendered for admin UI · GHCR push + SSH pull for staging deploy. Write an ADR on first implementation of each. See REQUIREMENTS.md §14.

## Working agreement

1. **Plan before code.** Before any non-trivial change, propose a plan and wait for confirmation.
2. **Phases are milestones.** Do not jump phases — finish Phase 1 before starting Phase 2 features.
3. **Tests alongside code.** No untested business logic ships.
4. **Secrets in `.env`**, never in commits. `.env.example` documents required vars.
5. **Migrations are immutable** once applied — never edit, always add new ones.
6. **ADRs for decisions.** Any deviation from `REQUIREMENTS.md` gets an ADR in `infra/docs/adr/`.
7. **German legal terms stay German** in code and UI: Eigentümer, WEG, Sondereigentum, Hausgeld, Umlaufbeschluss, Jahresabrechnung, Wirtschaftsplan, Beirat, etc.
8. **Ask when unclear.** The spec is the contract; clarify rather than guess.

## Stack at a glance

- Backend: Python 3.12 · FastAPI · SQLAlchemy 2 · Postgres 16 · Redis · Celery
- iOS: Swift · SwiftUI · SwiftData · iOS 17+
- Web: React 18 · TypeScript · Vite · Tailwind · shadcn/ui
- RAG: separate FastAPI service, pgvector or Qdrant
- Hosting: Hetzner Cloud (Nürnberg) for backend; Bluehost for marketing site only
- Auth: JWT (access + refresh) · Sign in with Apple · invite-code onboarding

## Domains

- `wagner-hausverwaltung.com` — marketing (Bluehost)
- `portal.wagner-hausverwaltung.com` — web portal
- `api.wagner-hausverwaltung.com` — backend API
- `ai.wagner-hausverwaltung.com` — RAG service

## Repo layout

```
backend/   FastAPI service
ios/       Xcode project (Swift)
web/       React portal
rag/       RAG microservice
infra/     Terraform, Ansible, ADRs, runbooks, DSGVO docs
```

See `REQUIREMENTS.md` §5 for the detailed structure.
