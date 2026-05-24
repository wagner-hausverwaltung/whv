from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1 import admin as admin_router
from app.api.v1 import admin_ui as admin_ui_router
from app.api.v1 import auth as auth_router
from app.api.v1 import circular as circular_router
from app.api.v1 import me as me_router
from app.api.v1 import tickets as tickets_router
from app.api.v1 import webhooks as webhooks_router
from app.auth.dependencies import NeedsLoginRedirect
from app.config import get_settings
from app.db import close_engine, init_engine, ping_db
from app.redis_client import close_redis, init_redis, ping_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_engine(settings.database_url)
    init_redis(settings.redis_url)
    try:
        yield
    finally:
        await close_redis()
        await close_engine()


app = FastAPI(
    title="WHV Backend",
    description="Wagner Hausverwaltung GmbH internal API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow the SPA portal to call the API cross-origin. credentials=False —
# the SPA carries the JWT in an Authorization header, not a cookie. Admin UI
# is same-origin (Caddy reverse-proxies admin.* → /admin-ui/) so it doesn't
# need an entry here.
_cors_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_cors_settings.portal_base_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.include_router(auth_router.router)
app.include_router(me_router.router)
app.include_router(admin_router.router)
app.include_router(webhooks_router.router)
app.include_router(admin_ui_router.router)
app.include_router(tickets_router.me_router)
app.include_router(tickets_router.admin_router)
app.include_router(circular_router.me_router)
app.include_router(circular_router.admin_router)


@app.exception_handler(NeedsLoginRedirect)
async def _needs_login_redirect(_: Request, __: NeedsLoginRedirect) -> RedirectResponse:
    return RedirectResponse("/admin-ui/login", status_code=status.HTTP_303_SEE_OTHER)


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
