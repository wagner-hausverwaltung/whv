# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app

# Storage tree for user uploads: avatars, property images, document
# library, resolution PDFs, ticket attachments. All written by the
# backend as the `app` user, so the parent has to exist and be owned
# by `app` before we drop privileges. Without this `mkdir(parents=True)`
# in the storage helpers raises PermissionError because /var/lib is
# root-owned in the base image — which surfaced on staging as a
# generic "Datei konnte nicht angehängt werden" on every upload.
# Hetzner Object Storage migration (REQUIREMENTS.md §1.4d iter 2)
# replaces this with bucket URLs and the chown becomes moot.
RUN mkdir -p /var/lib/whv && chown -R app:app /var/lib/whv

WORKDIR /app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
