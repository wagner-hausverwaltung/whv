from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.integrations.impower.client import ImpowerClient, get_impower_client
from app.integrations.impower.sync import (
    sync_contacts,
    sync_contracts,
    sync_documents,
    sync_properties,
    sync_units,
)
from app.models import Contact, Contract, Document, Property, Unit
from app.redis_client import get_redis
from app.schemas.webhook import ImpowerEntityType, ImpowerWebhookPayload

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# 5-minute dedupe window per (entity_type, entity_id, event_type). Set after
# successful processing — if processing raises, the next delivery isn't deduped
# so Impower's retry actually re-runs.
_DEDUPE_TTL_SECONDS = 300

# Entity types we currently mirror. Other types (buildings, invoices, messages)
# are acked silently until we add support.
_HANDLED_ENTITY_TYPES = ("properties", "units", "contracts", "contacts", "documents")


def _dedupe_key(payload: ImpowerWebhookPayload) -> str:
    return f"webhook:impower:{payload.entity_type}:{payload.entity_id}:{payload.event_type}"


async def _is_duplicate(redis: Redis, key: str) -> bool:
    return bool(await redis.exists(key))


async def _mark_processed(redis: Redis, key: str) -> None:
    await redis.set(key, "1", ex=_DEDUPE_TTL_SECONDS)


async def _handle_create_update(
    entity_type: ImpowerEntityType,
    session: AsyncSession,
    client: ImpowerClient,
) -> None:
    """v1: trigger a full re-sync of the entity type.

    Wasteful per event but correct. v2 should fetch the single entity by ID via
    new client methods (get_property/get_unit/...) and call a per-row upsert.
    """
    if entity_type == "properties":
        await sync_properties(session, client)
    elif entity_type == "units":
        await sync_units(session, client)
    elif entity_type == "contracts":
        await sync_contracts(session, client)
    elif entity_type == "contacts":
        await sync_contacts(session, client)
    elif entity_type == "documents":
        await sync_documents(session, client)


async def _handle_delete(
    entity_type: ImpowerEntityType,
    entity_id: int,
    session: AsyncSession,
) -> None:
    """Soft-delete the local row mirrored from Impower."""
    now = datetime.now(UTC)
    if entity_type == "properties":
        stmt = (
            update(Property)
            .where(Property.impower_id == entity_id, Property.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    elif entity_type == "units":
        stmt = (
            update(Unit)
            .where(Unit.impower_id == entity_id, Unit.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    elif entity_type == "contracts":
        stmt = (
            update(Contract)
            .where(Contract.impower_id == entity_id, Contract.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    elif entity_type == "contacts":
        stmt = (
            update(Contact)
            .where(Contact.impower_id == entity_id, Contact.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    elif entity_type == "documents":
        stmt = (
            update(Document)
            .where(Document.impower_id == entity_id, Document.deleted_at.is_(None))
            .values(deleted_at=now)
        )
    else:
        return
    await session.execute(stmt)
    await session.commit()


@router.post("/impower", status_code=200)
async def receive_impower_webhook(
    payload: ImpowerWebhookPayload,
    redis: Annotated[Redis, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[ImpowerClient, Depends(get_impower_client)],
) -> dict[str, Any]:
    key = _dedupe_key(payload)
    if await _is_duplicate(redis, key):
        return {"status": "duplicate", "key": key}

    handled = payload.entity_type in _HANDLED_ENTITY_TYPES
    if handled:
        if payload.event_type in ("CREATE", "UPDATE"):
            await _handle_create_update(payload.entity_type, session, client)
        elif payload.event_type == "DELETE":
            await _handle_delete(payload.entity_type, payload.entity_id, session)

    await _mark_processed(redis, key)
    return {
        "status": "processed" if handled else "ignored",
        "entity_type": payload.entity_type,
        "entity_id": payload.entity_id,
        "event_type": payload.event_type,
    }
