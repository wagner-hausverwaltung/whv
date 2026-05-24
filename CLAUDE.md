# CLAUDE.md

This is the Wagner Hausverwaltung GmbH (WHV) digital platform: backend, iOS app, web portal, and RAG service.

## Read first

**`REQUIREMENTS.md`** in the repo root is the authoritative spec. Read the relevant section before implementing anything. Do not proceed without context.

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
