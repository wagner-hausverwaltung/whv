from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from app.api.v1 import admin as admin_router
from app.api.v1 import auth as auth_router
from app.api.v1 import me as me_router
from app.api.v1 import webhooks as webhooks_router
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

app.include_router(auth_router.router)
app.include_router(me_router.router)
app.include_router(admin_router.router)
app.include_router(webhooks_router.router)


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
