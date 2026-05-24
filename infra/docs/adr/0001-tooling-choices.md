# ADR-0001: Backend tooling choices

- Date: 2026-05-24
- Status: Accepted

## Context

`REQUIREMENTS.md` specifies Python 3.12 + FastAPI + SQLAlchemy 2 + Postgres + Redis + Celery, with **ruff**, **mypy**, and **pytest** as the quality tools. It does not specify a package manager or project workflow tool. Phase 1.1 needs to pick one and commit to it before any other code is written.

## Decision

Adopt **`uv`** (Astral) as the package manager and project workflow tool for the backend (and the eventual `rag/` service).

- Single static binary, very fast resolver and installer
- PEP 621 `pyproject.toml` + lockfile (`uv.lock`) workflow
- Built-in Python toolchain management (`uv python install`)
- Same vendor as `ruff`; tight integration
- Reproducible Docker builds via `ghcr.io/astral-sh/uv` images
- `uv.lock` is committed; CI uses `uv sync --frozen` for deterministic installs

Companion tools (all specified in the spec):

- **ruff** — lint + format in one tool, with `select = ["E", "F", "I", "B", "UP", "N", "ASYNC", "SIM", "RUF"]`
- **mypy** — `strict = true`, Pydantic plugin enabled, scans `app/`
- **pytest** + **pytest-asyncio** — `asyncio_mode = "auto"`; FastAPI's `TestClient` (sync wrapper over `httpx`) for in-process API tests, which also drives lifespan

## Consequences

- Contributors install `uv` with a one-line script (documented in root `README.md`)
- CI uses `astral-sh/setup-uv` with `enable-cache: true` and `cache-dependency-glob: backend/uv.lock`
- The project is decoupled from any specific package manager — `pyproject.toml` is the source of truth and migration to Poetry or pip-tools later is mechanical
