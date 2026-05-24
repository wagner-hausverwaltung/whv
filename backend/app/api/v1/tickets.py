"""Ticket endpoints — owner-facing (/me/tickets) + admin (/admin/tickets).

Both routers live in this file so the shared state-transition logic stays in
one place. They mount under different prefixes via main.py.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.tickets import render_ticket_notification_email
from app.models import (
    AuditLog,
    Property,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketStatus,
    User,
    UserRole,
)
from app.schemas.ticket import (
    TicketCreateRequest,
    TicketDetailResponse,
    TicketMessageCreateRequest,
    TicketMessageResponse,
    TicketResponse,
    TicketStatusUpdateRequest,
)

me_router = APIRouter(prefix="/me/tickets", tags=["tickets"])
admin_router = APIRouter(prefix="/admin/tickets", tags=["tickets"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- shared helpers -----------------------------------------------------------


def _to_summary(t: Ticket) -> TicketResponse:
    return TicketResponse.model_validate(t)


def _to_detail(t: Ticket, messages: list[TicketMessage]) -> TicketDetailResponse:
    return TicketDetailResponse(
        id=t.id,
        property_id=t.property_id,
        created_by_user_id=t.created_by_user_id,
        assignee_user_id=t.assignee_user_id,
        category=t.category,
        status=t.status,
        subject=t.subject,
        last_message_at=t.last_message_at,
        created_at=t.created_at,
        closed_at=t.closed_at,
        messages=[TicketMessageResponse.model_validate(m) for m in messages],
    )


async def _load_messages(
    session: AsyncSession, ticket_id: uuid.UUID, *, include_internal: bool
) -> list[TicketMessage]:
    stmt = (
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at)
    )
    if not include_internal:
        stmt = stmt.where(TicketMessage.is_internal_note.is_(False))
    return list((await session.scalars(stmt)).all())


async def _owner_can_access(
    session: AsyncSession, user: User, ticket: Ticket
) -> bool:
    """True if the (non-Verwalter) user is allowed to see this ticket.

    Allow if: they created it, OR (ticket has a property AND they have a
    contract on it via contact_id_impower → contracts).
    """
    if ticket.created_by_user_id == user.id:
        return True
    if ticket.property_id is None or user.contact_id_impower is None:
        return False
    visible_stmt = _visible_properties_stmt(user).where(Property.id == ticket.property_id)
    prop = await session.scalar(visible_stmt)
    return prop is not None


async def _verwalter_recipients(session: AsyncSession, organization_id: uuid.UUID) -> list[str]:
    """Return the email addresses of all active Verwalter users in the org.

    Used to notify the team on new public ticket messages from owners. We
    fan-out to every Verwalter — once we grow beyond Luis, the assignee_user_id
    becomes the primary recipient and others are CC'd; for now everyone gets it.
    """
    rows = (
        await session.scalars(
            select(User).where(
                User.organization_id == organization_id,
                User.role == UserRole.VERWALTER,
                User.deleted_at.is_(None),
            )
        )
    ).all()
    return [u.email for u in rows]


async def _send_message_notification(
    *,
    email_client: EmailClient,
    ticket: Ticket,
    message: TicketMessage,
    recipients: list[str],
    sender_email: str,
) -> tuple[str | None, str | None]:
    """Best-effort send — returns (message_id, error_string). Caller is
    responsible for capturing the outcome in audit if desired."""
    if not recipients:
        return None, "no recipients"
    try:
        subject, html, text = render_ticket_notification_email(
            ticket_short_id=str(ticket.id)[:8],
            ticket_subject=ticket.subject,
            sender_email=sender_email,
            message_body=message.body,
        )
        msg_id = await email_client.send(
            to=",".join(recipients),
            subject=subject,
            html=html,
            text=text,
        )
        return msg_id, None
    except EmailError as exc:
        return None, str(exc)[:200]


# --- owner-facing routes ------------------------------------------------------


@me_router.get("", response_model=list[TicketResponse])
async def list_my_tickets(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
) -> list[TicketResponse]:
    stmt = select(Ticket).where(
        Ticket.organization_id == current_user.organization_id,
        Ticket.created_by_user_id == current_user.id,
    )
    if status_filter is not None:
        stmt = stmt.where(Ticket.status == status_filter)
    stmt = stmt.order_by(Ticket.last_message_at.desc())
    rows = (await session.scalars(stmt)).all()
    return [_to_summary(t) for t in rows]


@me_router.post(
    "",
    response_model=TicketDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_ticket(
    req: TicketCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> TicketDetailResponse:
    # Property-scope safety: if a property_id is supplied, verify the user
    # has access (Verwalter sees all; others restricted to their contracts).
    if req.property_id is not None:
        prop_stmt = _visible_properties_stmt(current_user).where(
            Property.id == req.property_id
        )
        prop = await session.scalar(prop_stmt)
        if prop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found",
            )

    now = datetime.now(UTC)
    ticket = Ticket(
        organization_id=current_user.organization_id,
        property_id=req.property_id,
        created_by_user_id=current_user.id,
        category=req.category,
        status=TicketStatus.NEU,
        subject=req.subject,
        last_message_at=now,
    )
    session.add(ticket)
    await session.flush()

    first_message = TicketMessage(
        ticket_id=ticket.id,
        author_user_id=current_user.id,
        body=req.body,
        is_internal_note=False,
    )
    session.add(first_message)

    audit_payload: dict[str, Any] = {
        "category": req.category.value,
        "property_id": str(req.property_id) if req.property_id else None,
    }
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="ticket_created",
            target_type="tickets",
            target_id=str(ticket.id),
            payload_json=audit_payload,
        )
    )

    # Notify Verwalter(s) of the new ticket. Best-effort — failure to send
    # doesn't roll back the ticket creation.
    recipients = await _verwalter_recipients(session, current_user.organization_id)
    await _send_message_notification(
        email_client=email_client,
        ticket=ticket,
        message=first_message,
        recipients=recipients,
        sender_email=current_user.email,
    )

    await session.commit()
    await session.refresh(ticket)
    return _to_detail(ticket, [first_message])


@me_router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_my_ticket(
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketDetailResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if current_user.role != UserRole.VERWALTER and not await _owner_can_access(
        session, current_user, ticket
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
        )
    # Owners never see internal notes; Verwalter using /me/* shouldn't be
    # surprised either (admin endpoint exposes them).
    messages = await _load_messages(session, ticket.id, include_internal=False)
    return _to_detail(ticket, messages)


@me_router.post(
    "/{ticket_id}/messages",
    response_model=TicketMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_my_message(
    ticket_id: uuid.UUID,
    req: TicketMessageCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> TicketMessageResponse:
    if req.is_internal_note:
        # Owners cannot post internal notes. Silently coerce to False so a
        # malicious client can't sneak one through the owner endpoint.
        req.is_internal_note = False

    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.status == TicketStatus.GESCHLOSSEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticket ist geschlossen — kein Antworten mehr möglich.",
        )
    if current_user.role != UserRole.VERWALTER and not await _owner_can_access(
        session, current_user, ticket
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
        )

    now = datetime.now(UTC)
    message = TicketMessage(
        ticket_id=ticket.id,
        author_user_id=current_user.id,
        body=req.body,
        is_internal_note=False,
    )
    session.add(message)
    ticket.last_message_at = now
    # Owner replying → status becomes OFFEN (resets WARTET_AUF_KUNDE).
    if ticket.status in (TicketStatus.NEU, TicketStatus.WARTET_AUF_KUNDE):
        ticket.status = TicketStatus.OFFEN

    recipients = await _verwalter_recipients(session, current_user.organization_id)
    await _send_message_notification(
        email_client=email_client,
        ticket=ticket,
        message=message,
        recipients=recipients,
        sender_email=current_user.email,
    )

    await session.commit()
    await session.refresh(message)
    return TicketMessageResponse.model_validate(message)


@me_router.post("/{ticket_id}/close", response_model=TicketResponse)
async def close_my_ticket(
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
            Ticket.created_by_user_id == current_user.id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.status == TicketStatus.GESCHLOSSEN:
        return _to_summary(ticket)

    now = datetime.now(UTC)
    ticket.status = TicketStatus.GESCHLOSSEN
    ticket.closed_at = now
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="ticket_closed",
            target_type="tickets",
            target_id=str(ticket.id),
            payload_json={"closed_by": "owner"},
        )
    )
    await session.commit()
    await session.refresh(ticket)
    return _to_summary(ticket)


# --- admin routes -------------------------------------------------------------


@admin_router.get("", response_model=list[TicketResponse])
async def list_all_tickets(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    category: TicketCategory | None = None,
) -> list[TicketResponse]:
    stmt = select(Ticket).where(Ticket.organization_id == current_user.organization_id)
    if status_filter is not None:
        stmt = stmt.where(Ticket.status == status_filter)
    if category is not None:
        stmt = stmt.where(Ticket.category == category)
    stmt = stmt.order_by(Ticket.last_message_at.desc()).limit(200)
    rows = (await session.scalars(stmt)).all()
    return [_to_summary(t) for t in rows]


@admin_router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketDetailResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    messages = await _load_messages(session, ticket.id, include_internal=True)
    return _to_detail(ticket, messages)


@admin_router.post(
    "/{ticket_id}/messages",
    response_model=TicketMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_admin_message(
    ticket_id: uuid.UUID,
    req: TicketMessageCreateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> TicketMessageResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    now = datetime.now(UTC)
    message = TicketMessage(
        ticket_id=ticket.id,
        author_user_id=current_user.id,
        body=req.body,
        is_internal_note=req.is_internal_note,
    )
    session.add(message)
    ticket.last_message_at = now

    # Verwalter replying (non-internal) → status WARTET_AUF_KUNDE.
    if not req.is_internal_note and ticket.status in (
        TicketStatus.NEU,
        TicketStatus.OFFEN,
    ):
        ticket.status = TicketStatus.WARTET_AUF_KUNDE

    # Notify the owner ONLY when this is a public message (not an internal note).
    if not req.is_internal_note:
        owner = await session.scalar(
            select(User).where(User.id == ticket.created_by_user_id)
        )
        if owner is not None and owner.deleted_at is None:
            await _send_message_notification(
                email_client=email_client,
                ticket=ticket,
                message=message,
                recipients=[owner.email],
                sender_email=current_user.email,
            )

    await session.commit()
    await session.refresh(message)
    return TicketMessageResponse.model_validate(message)


@admin_router.patch("/{ticket_id}", response_model=TicketResponse)
async def patch_ticket(
    ticket_id: uuid.UUID,
    req: TicketStatusUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    old_status = ticket.status
    ticket.status = req.status
    if req.assignee_user_id is not None:
        # Validate assignee is in same org + active.
        assignee = await session.scalar(
            select(User).where(
                User.id == req.assignee_user_id,
                User.organization_id == current_user.organization_id,
                User.deleted_at.is_(None),
            )
        )
        if assignee is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignee not found in organization",
            )
        ticket.assignee_user_id = req.assignee_user_id

    if req.status == TicketStatus.GESCHLOSSEN and ticket.closed_at is None:
        ticket.closed_at = datetime.now(UTC)
    elif req.status != TicketStatus.GESCHLOSSEN:
        # Re-opening clears closed_at; legitimate when a customer responds
        # after the Verwalter prematurely closed.
        ticket.closed_at = None

    if old_status != req.status:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="ticket_status_changed",
                target_type="tickets",
                target_id=str(ticket.id),
                payload_json={
                    "from": old_status.value,
                    "to": req.status.value,
                },
            )
        )

    await session.commit()
    await session.refresh(ticket)
    return _to_summary(ticket)


