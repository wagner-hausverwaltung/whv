# Wagner Hausverwaltung — Digital Platform

Backend, iOS app, web portal, and RAG service for **Wagner Hausverwaltung GmbH**.

- **Authoritative spec:** [`REQUIREMENTS.md`](REQUIREMENTS.md) — read the relevant section before changing anything
- **Working agreement:** [`CLAUDE.md`](CLAUDE.md) — plan before code, phases are milestones, tests alongside code
- **Architecture decisions:** [`infra/docs/adr/`](infra/docs/adr/)

## Current phase

**Phase 1.1 — Project bootstrap.** Backend skeleton, healthchecks, CI, docker-compose. No business logic or schemas yet — that begins in Phase 1.2.

## Quick start

### Prereqs

- [`uv`](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker + Docker Compose
- Python 3.12 (installed automatically by `uv`)

### Local development (hybrid: infra in docker, backend on host)

```bash
cp .env.example .env
docker compose up -d postgres redis
cd backend
uv sync
uv run uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

### Full stack via Docker

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/healthz   # → {"status":"ok"}
curl http://localhost:8000/readyz    # → {"status":"ok","deps":{"postgres":true,"redis":true}}
```

### Quality checks

```bash
cd backend
uv run pytest                # requires postgres + redis reachable
uv run ruff check .
uv run ruff format --check .
uv run mypy app/
```

## Repo layout

See [`REQUIREMENTS.md` §5](REQUIREMENTS.md) for the canonical layout.

```
backend/    FastAPI service
ios/        Xcode project           (not yet scaffolded)
web/        React portal            (not yet scaffolded)
rag/        RAG microservice        (not yet scaffolded)
infra/      ADRs, runbooks, DSGVO docs
```
