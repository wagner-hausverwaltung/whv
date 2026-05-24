import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.constants import WHV_ORGANIZATION_ID
from app.db import get_session
from app.integrations.email.client import EmailClient, get_email_client
from app.integrations.email.inbound import (
    InboundEmailParseError,
    parse_ses_sns_payload,
)
from app.integrations.email.tickets import render_ticket_notification_email
from app.integrations.impower.client import ImpowerClient, get_impower_client
from app.integrations.impower.sync import (
    sync_contacts,
    sync_contracts,
    sync_documents,
    sync_properties,
    sync_units,
)
from app.integrations.sns.validator import SignatureError, verify
from app.models import (
    AuditLog,
    Contact,
    Contract,
    Document,
    Property,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketMessageSource,
    TicketStatus,
    Unit,
    User,
)
from app.redis_client import get_redis
from app.schemas.webhook import ImpowerEntityType, ImpowerWebhookPayload

logger = logging.getLogger(__name__)

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


# --- Email inbound (SES → SNS → here) -----------------------------------------
# See infra/docs/email-inbound-aws-ses.md for the AWS-side setup.


async def _resolve_ticket_by_ref(
    session: AsyncSession, organization_id: Any, ticket_ref: str
) -> Ticket | None:
    """Look up a ticket whose UUID starts with `ticket_ref` (8 hex chars).

    Returns None on no-match or ambiguous match (more than one ticket whose
    UUID starts with that prefix — exceedingly unlikely with UUIDv7, but
    we'd rather create a fresh ticket than splice into the wrong thread).
    """
    matches = (
        await session.scalars(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.id.cast(__import__("sqlalchemy").String).ilike(f"{ticket_ref}%"),
            )
        )
    ).all()
    if len(matches) != 1:
        return None
    return matches[0]


async def _resolve_author_user(
    session: AsyncSession, organization_id: Any, email: str
) -> User | None:
    result: User | None = await session.scalar(
        select(User).where(
            User.email == email,
            User.organization_id == organization_id,
            User.deleted_at.is_(None),
        )
    )
    return result


@router.post("/email/inbound", status_code=200)
async def email_inbound(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """SES → SNS → here. Verifies signature, parses MIME, routes to a ticket.

    Handles two SNS message types:
      - SubscriptionConfirmation: visit the SubscribeURL once (this is how
        SNS proves we control the endpoint when we create the subscription)
      - Notification: parse SES envelope → MIME → resolve / create ticket
        → insert message row → fan-out email notifications

    Idempotency: ticket_messages.email_message_id is UNIQUE; duplicate SNS
    retries of the same SES email collide and silently no-op.
    """
    body = await request.body()
    try:
        import json

        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("email_inbound: invalid JSON body: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad JSON") from exc

    try:
        verify(message)
    except SignatureError as exc:
        logger.warning("email_inbound: signature failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid SNS signature"
        ) from exc

    msg_type = message.get("Type")

    # --- Subscription confirmation handshake ----------------------------------
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = message.get("SubscribeURL")
        if not subscribe_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SubscriptionConfirmation missing SubscribeURL",
            )
        # Visit the URL to confirm. AWS returns HTTP 200 once it's done.
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(subscribe_url)
        logger.info("email_inbound: subscription confirmed")
        return {"status": "subscription_confirmed"}

    if msg_type != "Notification":
        # UnsubscribeConfirmation or unknown — log + ack so SNS doesn't retry.
        logger.info("email_inbound: ignoring SNS Type=%s", msg_type)
        return {"status": "ignored", "type": msg_type}

    # --- Notification ---------------------------------------------------------
    try:
        parsed = parse_ses_sns_payload(message.get("Message", ""))
    except InboundEmailParseError as exc:
        logger.warning("email_inbound: parse failed: %s", exc)
        # Return 200 so SNS doesn't retry — the payload is malformed and
        # won't fix itself on retry.
        return {"status": "parse_error", "detail": str(exc)}

    if not parsed.spam_pass or not parsed.virus_pass:
        logger.info(
            "email_inbound: dropping spam/virus message from %s (spam=%s virus=%s)",
            parsed.sender_email,
            parsed.spam_pass,
            parsed.virus_pass,
        )
        session.add(
            AuditLog(
                organization_id=WHV_ORGANIZATION_ID,
                actor_user_id=None,
                action="ticket_email_rejected",
                target_type="email",
                target_id=parsed.message_id or "",
                payload_json={
                    "sender": parsed.sender_email,
                    "subject": parsed.subject,
                    "spam_pass": parsed.spam_pass,
                    "virus_pass": parsed.virus_pass,
                },
            )
        )
        await session.commit()
        return {"status": "rejected_spam_or_virus"}

    # Idempotency: if we've already stored a message with this email_message_id,
    # SNS is retrying — ack silently.
    if parsed.message_id:
        existing = await session.scalar(
            select(TicketMessage).where(
                TicketMessage.email_message_id == parsed.message_id
            )
        )
        if existing is not None:
            return {"status": "duplicate", "ticket_id": str(existing.ticket_id)}

    # Resolve author by email (org-scoped). If unknown, we'll set
    # author_user_id=NULL and stash the sender on the message + ticket.
    author = await _resolve_author_user(session, WHV_ORGANIZATION_ID, parsed.sender_email)

    # Resolve or create the ticket.
    ticket: Ticket | None = None
    if parsed.ticket_ref:
        ticket = await _resolve_ticket_by_ref(session, WHV_ORGANIZATION_ID, parsed.ticket_ref)
    created_new = False
    now = datetime.now(UTC)
    if ticket is None:
        # New ticket from this email. Subject + body become the first message.
        ticket = Ticket(
            organization_id=WHV_ORGANIZATION_ID,
            created_by_user_id=author.id if author else None,
            external_sender_email=None if author else parsed.sender_email,
            category=TicketCategory.SONSTIGES,
            status=TicketStatus.NEU,
            subject=parsed.subject or "(ohne Betreff)",
            last_message_at=now,
        )
        session.add(ticket)
        await session.flush()
        created_new = True
        session.add(
            AuditLog(
                organization_id=WHV_ORGANIZATION_ID,
                actor_user_id=author.id if author else None,
                action="ticket_created_via_email",
                target_type="tickets",
                target_id=str(ticket.id),
                payload_json={
                    "sender": parsed.sender_email,
                    "message_id": parsed.message_id,
                    "subject": parsed.subject,
                },
            )
        )

    elif ticket.status == TicketStatus.GESCHLOSSEN:
        # Replying to a closed ticket reopens it (matches the portal "owner
        # replies → OFFEN" semantic).
        ticket.status = TicketStatus.OFFEN
        ticket.closed_at = None

    message_row = TicketMessage(
        ticket_id=ticket.id,
        author_user_id=author.id if author else None,
        external_sender_email=None if author else parsed.sender_email,
        body=parsed.body or "(leerer Text)",
        is_internal_note=False,
        source=TicketMessageSource.EMAIL,
        email_message_id=parsed.message_id,
    )
    session.add(message_row)
    ticket.last_message_at = now
    if not created_new and ticket.status in (TicketStatus.NEU, TicketStatus.WARTET_AUF_KUNDE):
        ticket.status = TicketStatus.OFFEN

    # Notify Verwalter(s) + creator (if different from sender) + named participants.
    from app.api.v1.tickets import (
        _dedupe,
        _participant_emails,
        _verwalter_recipients,
    )

    recipients = await _verwalter_recipients(session, WHV_ORGANIZATION_ID)
    if not created_new:
        creator_email: str | None = None
        if ticket.created_by_user_id:
            creator = await session.scalar(select(User).where(User.id == ticket.created_by_user_id))
            if creator and creator.deleted_at is None:
                creator_email = creator.email
        elif ticket.external_sender_email:
            creator_email = ticket.external_sender_email
        if creator_email:
            recipients.append(creator_email)
        recipients.extend(await _participant_emails(session, ticket.id))
    recipients = [r for r in _dedupe(recipients) if r != parsed.sender_email]

    if recipients:
        try:
            short_id = str(ticket.id)[:8]
            tagged_subject = (
                ticket.subject
                if f"[#{short_id}]" in ticket.subject
                else f"[#{short_id}] {ticket.subject}"
            )
            subject_line, html, text = render_ticket_notification_email(
                ticket_short_id=short_id,
                ticket_subject=tagged_subject,
                sender_email=parsed.sender_email,
                message_body=parsed.body,
            )
            await email_client.send(
                to=",".join(recipients),
                subject=subject_line,
                html=html,
                text=text,
                headers=_threading_headers(parsed),
            )
        except Exception as exc:
            logger.warning("email_inbound: notify failed: %s", exc)

    await session.commit()
    await session.refresh(ticket)
    _ = settings  # currently unused; reserved for future config (rate limits etc.)
    return {
        "status": "created" if created_new else "appended",
        "ticket_id": str(ticket.id),
    }


def _threading_headers(parsed: Any) -> dict[str, str]:
    """Build In-Reply-To + References so the outbound notification threads
    properly in Gmail / Outlook clients."""
    headers: dict[str, str] = {}
    if parsed.message_id:
        headers["In-Reply-To"] = parsed.message_id
        # Concatenate the existing References chain (if any) with the new ID
        # so the thread builds up cleanly across many replies.
        if parsed.references:
            headers["References"] = f"{parsed.references} {parsed.message_id}".strip()
        else:
            headers["References"] = parsed.message_id
    return headers
