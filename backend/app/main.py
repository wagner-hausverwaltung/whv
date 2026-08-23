from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import accounting as accounting_router
from app.api.v1 import admin as admin_router
from app.api.v1 import admin_assistant as admin_assistant_router
from app.api.v1 import announcements as announcements_router
from app.api.v1 import assistant as assistant_router
from app.api.v1 import auth as auth_router
from app.api.v1 import briefing as briefing_router
from app.api.v1 import calendar as calendar_router
from app.api.v1 import call_directory as call_directory_router
from app.api.v1 import circular as circular_router
from app.api.v1 import etv as etv_router
from app.api.v1 import me as me_router
from app.api.v1 import meters as meters_router
from app.api.v1 import offers as offers_router
from app.api.v1 import supplier_contracts as supplier_contracts_router
from app.api.v1 import tickets as tickets_router
from app.api.v1 import trips as trips_router
from app.api.v1 import vollmachten as vollmachten_router
from app.api.v1 import webhooks as webhooks_router
from app.config import get_settings
from app.db import close_engine, init_engine, ping_db
from app.rag.db import close_rag_engine, init_rag_engine, init_rag_store
from app.redis_client import close_redis, init_redis, ping_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_engine(settings.database_url)
    init_redis(settings.redis_url)
    # RAG assistant ships dark until rag_enabled; only then do we connect
    # to + bootstrap the separate pgvector store (ADR-0013).
    if settings.rag_enabled:
        init_rag_engine(settings.rag_database_url)
        await init_rag_store()
    try:
        yield
    finally:
        await close_redis()
        await close_engine()
        if settings.rag_enabled:
            await close_rag_engine()


# Cached settings drive both the docs gate and the CORS allow-list below;
# this is the same instance the rest of the app sees.
_settings = get_settings()
_is_dev = _settings.app_env == "dev"

app = FastAPI(
    title="WHV Backend",
    description="Wagner Hausverwaltung GmbH internal API",
    version="0.1.0",
    lifespan=lifespan,
    # Swagger / ReDoc / the OpenAPI schema enumerate the entire API surface
    # (every route, every model). Useful in dev, needless attack-surface in
    # prod — serve them only when app_env is dev.
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
)

# CORS: allow the SPA to call the API cross-origin. credentials=False —
# the SPA carries the JWT in an Authorization header, not a cookie. The
# same SPA bundle is served from two hosts (portal.* + admin.*), so both
# origins need to be in the allow-list. admin_base_url is empty in dev
# (single Vite origin); on staging/prod it points at admin.*.
_cors_allowed = [_settings.portal_base_url]
if _settings.admin_base_url:
    _cors_allowed.append(_settings.admin_base_url)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.include_router(auth_router.router)
app.include_router(me_router.router)
app.include_router(assistant_router.router)
app.include_router(admin_router.router)
app.include_router(admin_assistant_router.router)
app.include_router(webhooks_router.router)
app.include_router(tickets_router.me_router)
app.include_router(tickets_router.admin_router)
app.include_router(meters_router.me_router)
app.include_router(meters_router.admin_router)
app.include_router(offers_router.admin_router)
app.include_router(supplier_contracts_router.admin_router)
app.include_router(trips_router.me_router)
app.include_router(call_directory_router.me_router)
app.include_router(briefing_router.me_router)
app.include_router(trips_router.admin_router)
app.include_router(vollmachten_router.me_router)
app.include_router(vollmachten_router.admin_router)
app.include_router(calendar_router.me_router)
app.include_router(calendar_router.admin_router)
app.include_router(circular_router.me_router)
app.include_router(circular_router.admin_router)
app.include_router(accounting_router.me_router)
app.include_router(accounting_router.admin_router)
app.include_router(circular_router.public_router)
app.include_router(announcements_router.me_router)
app.include_router(announcements_router.admin_router)
app.include_router(etv_router.me_router)
app.include_router(etv_router.admin_router)

# User-uploaded avatars. StaticFiles wants the directory to exist at mount
# time; we attempt to create it but tolerate a permission failure (common
# in dev when the default /var/lib path needs root). On failure the mount
# is skipped — the upload endpoint still works as long as the writer can
# eventually create the dir.
_avatar_dir = Path(_settings.avatar_dir)
try:
    _avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/me/avatars",
        StaticFiles(directory=str(_avatar_dir)),
        name="avatars",
    )
except OSError:
    pass

# Property hero photos are NOT mounted as public StaticFiles — they're
# served by the authenticated GET /admin/property-images/{file} endpoint
# (app/api/v1/admin.py) so the bytes aren't world-readable. The storage
# dir is created lazily on first upload (write_property_image).


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["meta"])
async def readyz() -> JSONResponse:
    db_ok = await ping_db()
    redis_ok = await ping_redis()
    healthy = db_ok and redis_ok
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ok" if healthy else "degraded",
            "deps": {"postgres": db_ok, "redis": redis_ok},
        },
    )
