"""Ticket endpoints — owner-facing (/me/tickets) + admin (/admin/tickets).

Both routers live in this file so the shared state-transition logic stays in
one place. They mount under different prefixes via main.py.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
    TicketParticipant,
    TicketShareScope,
    TicketStatus,
    User,
    UserRole,
)
from app.schemas.ticket import (
    TicketCreateRequest,
    TicketDetailResponse,
    TicketMessageCreateRequest,
    TicketMessageResponse,
    TicketParticipantAddRequest,
    TicketParticipantResponse,
    TicketResponse,
    TicketShareScopeUpdateRequest,
    TicketStatusUpdateRequest,
)

me_router = APIRouter(prefix="/me/tickets", tags=["tickets"])
admin_router = APIRouter(prefix="/admin/tickets", tags=["tickets"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- shared helpers -----------------------------------------------------------


def _to_summary(t: Ticket) -> TicketResponse:
    return TicketResponse.model_validate(t)


async def _load_participants(
    session: AsyncSession, ticket_id: uuid.UUID
) -> list[TicketParticipantResponse]:
    rows = (
        await session.execute(
            select(TicketParticipant, User.email)
            .join(User, User.id == TicketParticipant.user_id)
            .where(TicketParticipant.ticket_id == ticket_id)
            .order_by(TicketParticipant.added_at)
        )
    ).all()
    return [
        TicketParticipantResponse(
            user_id=p.user_id,
            email=email,
            added_by_user_id=p.added_by_user_id,
            added_at=p.added_at,
        )
        for p, email in rows
    ]


async def _to_detail(
    t: Ticket, messages: list[TicketMessage], session: AsyncSession
) -> TicketDetailResponse:
    participants = await _load_participants(session, t.id)
    # Resolve author emails in one batch so the SPA can render thread rows
    # without N follow-up requests. Hard-deleted users → email is None.
    author_ids = {m.author_user_id for m in messages if m.author_user_id}
    author_emails: dict[uuid.UUID, str] = {}
    if author_ids:
        author_rows = (
            await session.scalars(select(User).where(User.id.in_(author_ids)))
        ).all()
        author_emails = {u.id: u.email for u in author_rows}
    message_resps = [
        TicketMessageResponse(
            id=m.id,
            ticket_id=m.ticket_id,
            author_user_id=m.author_user_id,
            author_email=(
                author_emails.get(m.author_user_id) if m.author_user_id else None
            ),
            body=m.body,
            is_internal_note=m.is_internal_note,
            created_at=m.created_at,
        )
        for m in messages
    ]
    return TicketDetailResponse(
        id=t.id,
        property_id=t.property_id,
        created_by_user_id=t.created_by_user_id,
        assignee_user_id=t.assignee_user_id,
        category=t.category,
        status=t.status,
        share_scope=t.share_scope,
        subject=t.subject,
        last_message_at=t.last_message_at,
        created_at=t.created_at,
        closed_at=t.closed_at,
        messages=message_resps,
        participants=participants,
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


async def _owner_can_access(session: AsyncSession, user: User, ticket: Ticket) -> bool:
    """True if the (non-Verwalter) user is allowed to see this ticket.

    Allow if any of:
    - they created it
    - they are an explicit named participant (ticket_participants row)
    - share_scope=PROPERTY AND they have a contract on ticket.property_id
    """
    if ticket.created_by_user_id == user.id:
        return True
    is_named_participant = await session.scalar(
        select(TicketParticipant).where(
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.user_id == user.id,
        )
    )
    if is_named_participant is not None:
        return True
    if (
        ticket.share_scope == TicketShareScope.PROPERTY
        and ticket.property_id is not None
        and user.contact_id_impower is not None
    ):
        visible_stmt = _visible_properties_stmt(user).where(Property.id == ticket.property_id)
        prop = await session.scalar(visible_stmt)
        return prop is not None
    return False


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


async def _participant_emails(session: AsyncSession, ticket_id: uuid.UUID) -> list[str]:
    """Email addresses of the explicit named participants on a ticket.

    Property-scope viewers (share_scope=PROPERTY) are NOT included here — they
    can see the ticket if they visit the portal, but a broad property-wide
    email fan-out on every message would spam too widely. Only people who were
    *explicitly* added (via ticket_participants) get the message email.
    """
    rows = (
        await session.execute(
            select(User.email)
            .join(TicketParticipant, TicketParticipant.user_id == User.id)
            .where(
                TicketParticipant.ticket_id == ticket_id,
                User.deleted_at.is_(None),
            )
        )
    ).all()
    return [email for (email,) in rows]


def _dedupe(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for e in emails:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


async def _latest_email_thread_headers(
    session: AsyncSession, ticket_id: uuid.UUID
) -> dict[str, str]:
    """Build In-Reply-To / References headers for outbound replies on tickets
    that were started/continued by email. Empty dict if the ticket has no
    email-sourced messages — outbound is then a fresh thread.
    """
    latest = await session.scalar(
        select(TicketMessage)
        .where(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.email_message_id.is_not(None),
        )
        .order_by(TicketMessage.created_at.desc())
        .limit(1)
    )
    if latest is None or latest.email_message_id is None:
        return {}
    return {
        "In-Reply-To": latest.email_message_id,
        "References": latest.email_message_id,
    }


async def _send_message_notification(
    *,
    email_client: EmailClient,
    ticket: Ticket,
    message: TicketMessage,
    recipients: list[str],
    sender_email: str,
    headers: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Best-effort send — returns (message_id, error_string). Caller is
    responsible for capturing the outcome in audit if desired."""
    if not recipients:
        return None, "no recipients"
    try:
        subject, html, text = render_ticket_notification_email(
            # 16 hex chars (no dashes) — reaches into UUIDv7's version + rand_a
            # bits so two tickets created in the same millisecond can be
            # distinguished. Must stay in sync with the inbound subject regex
            # in app/integrations/email/inbound.py.
            ticket_short_id=ticket.id.hex[:16],
            ticket_subject=ticket.subject,
            sender_email=sender_email,
            message_body=message.body,
        )
        msg_id = await email_client.send(
            to=",".join(recipients),
            subject=subject,
            html=html,
            text=text,
            headers=headers,
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
        prop_stmt = _visible_properties_stmt(current_user).where(Property.id == req.property_id)
        prop = await session.scalar(prop_stmt)
        if prop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found",
            )

    # PROPERTY share-scope requires property_id; reject the inconsistent combo
    # rather than silently demoting (a PROPERTY ticket without a property is
    # always PRIVATE in practice, but the request was clearly mistaken).
    if req.share_scope == TicketShareScope.PROPERTY and req.property_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="share_scope=PROPERTY benötigt eine property_id.",
        )

    now = datetime.now(UTC)
    ticket = Ticket(
        organization_id=current_user.organization_id,
        property_id=req.property_id,
        created_by_user_id=current_user.id,
        category=req.category,
        status=TicketStatus.NEU,
        share_scope=req.share_scope,
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
    # doesn't roll back the ticket creation. No participants yet on a brand-new
    # ticket, so we only fan out to Verwalter here.
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
    return await _to_detail(ticket, [first_message], session)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    # Owners never see internal notes; Verwalter using /me/* shouldn't be
    # surprised either (admin endpoint exposes them).
    messages = await _load_messages(session, ticket.id, include_internal=False)
    return await _to_detail(ticket, messages, session)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

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

    # Owner reply → notify Verwalter + creator + external sender (if the
    # ticket originated by email from a non-user) + all explicit participants
    # (excluding the author of this reply, since they already know).
    creator = (
        await session.scalar(select(User).where(User.id == ticket.created_by_user_id))
        if ticket.created_by_user_id
        else None
    )
    recipients = _dedupe(
        [
            *(await _verwalter_recipients(session, current_user.organization_id)),
            *(await _participant_emails(session, ticket.id)),
            *([creator.email] if creator and creator.deleted_at is None else []),
            *([ticket.external_sender_email] if ticket.external_sender_email else []),
        ]
    )
    recipients = [e for e in recipients if e != current_user.email]
    await _send_message_notification(
        email_client=email_client,
        ticket=ticket,
        message=message,
        recipients=recipients,
        sender_email=current_user.email,
        headers=await _latest_email_thread_headers(session, ticket.id),
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
    return await _to_detail(ticket, messages, session)


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

    # Notify creator (or external sender if the ticket came in by email) +
    # explicit participants. Internal notes stay Verwalter-only — no email.
    # Property-scope viewers are intentionally NOT fanned out to here.
    if not req.is_internal_note:
        owner = (
            await session.scalar(select(User).where(User.id == ticket.created_by_user_id))
            if ticket.created_by_user_id
            else None
        )
        recipients = _dedupe(
            [
                *([owner.email] if owner and owner.deleted_at is None else []),
                *([ticket.external_sender_email] if ticket.external_sender_email else []),
                *(await _participant_emails(session, ticket.id)),
            ]
        )
        if recipients:
            await _send_message_notification(
                email_client=email_client,
                ticket=ticket,
                message=message,
                recipients=recipients,
                sender_email=current_user.email,
                headers=await _latest_email_thread_headers(session, ticket.id),
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


# --- Participant management ---------------------------------------------------
# Shared between the /me and /admin routers via small wrapper handlers below.
# Only the ticket creator OR a Verwalter may add/remove participants.


async def _can_manage_participants(session: AsyncSession, user: User, ticket: Ticket) -> bool:
    if user.role == UserRole.VERWALTER:
        return True
    return ticket.created_by_user_id == user.id


async def _add_participant(
    *,
    session: AsyncSession,
    ticket: Ticket,
    actor: User,
    email: str,
) -> TicketParticipantResponse:
    target = await session.scalar(
        select(User).where(
            User.email == email.strip().lower(),
            User.organization_id == ticket.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Kein Konto mit dieser E-Mail-Adresse in der Organisation gefunden. "
                "Die Person muss erst eingeladen werden und das Konto aktivieren."
            ),
        )
    if target.id == ticket.created_by_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ersteller ist bereits Teilnehmer.",
        )
    existing = await session.scalar(
        select(TicketParticipant).where(
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.user_id == target.id,
        )
    )
    if existing is not None:
        return TicketParticipantResponse(
            user_id=target.id,
            email=target.email,
            added_by_user_id=existing.added_by_user_id,
            added_at=existing.added_at,
        )

    row = TicketParticipant(
        ticket_id=ticket.id,
        user_id=target.id,
        added_by_user_id=actor.id,
    )
    session.add(row)
    session.add(
        AuditLog(
            organization_id=ticket.organization_id,
            actor_user_id=actor.id,
            action="ticket_participant_added",
            target_type="tickets",
            target_id=str(ticket.id),
            payload_json={"user_id": str(target.id), "email": target.email},
        )
    )
    await session.commit()
    await session.refresh(row)
    return TicketParticipantResponse(
        user_id=target.id,
        email=target.email,
        added_by_user_id=row.added_by_user_id,
        added_at=row.added_at,
    )


async def _remove_participant(
    *,
    session: AsyncSession,
    ticket: Ticket,
    actor: User,
    user_id: uuid.UUID,
) -> None:
    row = await session.scalar(
        select(TicketParticipant).where(
            TicketParticipant.ticket_id == ticket.id,
            TicketParticipant.user_id == user_id,
        )
    )
    if row is None:
        return  # idempotent
    await session.delete(row)
    session.add(
        AuditLog(
            organization_id=ticket.organization_id,
            actor_user_id=actor.id,
            action="ticket_participant_removed",
            target_type="tickets",
            target_id=str(ticket.id),
            payload_json={"user_id": str(user_id)},
        )
    )
    await session.commit()


# --- Owner-facing share-scope + participants ---------------------------------


@me_router.patch("/{ticket_id}/share-scope", response_model=TicketResponse)
async def update_my_share_scope(
    ticket_id: uuid.UUID,
    req: TicketShareScopeUpdateRequest,
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
    if req.share_scope == TicketShareScope.PROPERTY and ticket.property_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="share_scope=PROPERTY benötigt eine property_id.",
        )
    ticket.share_scope = req.share_scope
    await session.commit()
    await session.refresh(ticket)
    return _to_summary(ticket)


@me_router.post(
    "/{ticket_id}/participants",
    response_model=TicketParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_my_participant(
    ticket_id: uuid.UUID,
    req: TicketParticipantAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketParticipantResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if not await _can_manage_participants(session, current_user, ticket):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return await _add_participant(
        session=session, ticket=ticket, actor=current_user, email=req.email
    )


@me_router.delete(
    "/{ticket_id}/participants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_my_participant(
    ticket_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if not await _can_manage_participants(session, current_user, ticket):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    await _remove_participant(session=session, ticket=ticket, actor=current_user, user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Admin-facing share-scope + participants ---------------------------------


@admin_router.patch("/{ticket_id}/share-scope", response_model=TicketResponse)
async def update_admin_share_scope(
    ticket_id: uuid.UUID,
    req: TicketShareScopeUpdateRequest,
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
    if req.share_scope == TicketShareScope.PROPERTY and ticket.property_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="share_scope=PROPERTY benötigt eine property_id.",
        )
    ticket.share_scope = req.share_scope
    await session.commit()
    await session.refresh(ticket)
    return _to_summary(ticket)


@admin_router.post(
    "/{ticket_id}/participants",
    response_model=TicketParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_admin_participant(
    ticket_id: uuid.UUID,
    req: TicketParticipantAddRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketParticipantResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return await _add_participant(
        session=session, ticket=ticket, actor=current_user, email=req.email
    )


@admin_router.delete(
    "/{ticket_id}/participants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_admin_participant(
    ticket_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    await _remove_participant(session=session, ticket=ticket, actor=current_user, user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
