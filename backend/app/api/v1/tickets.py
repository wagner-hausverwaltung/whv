"""Ticket endpoints — owner-facing (/me/tickets) + admin (/admin/tickets).

Both routers live in this file so the shared state-transition logic stays in
one place. They mount under different prefixes via main.py.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.tickets import (
    render_ticket_notification_email,
    render_ticket_shared_email,
)
from app.integrations.storage.ticket_attachments import (
    TicketAttachmentStorageError,
    attachment_path,
    delete_attachment,
    write_attachment,
)
from app.models import (
    AuditLog,
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    NotificationCategory,
    NotificationChannel,
    Property,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketMessageAttachment,
    TicketParticipant,
    TicketShareScope,
    TicketStatus,
    User,
    UserRole,
)
from app.schemas.ticket import (
    TicketCreateRequest,
    TicketDetailResponse,
    TicketMessageAttachmentResponse,
    TicketMessageCreateRequest,
    TicketMessageResponse,
    TicketParticipantAddRequest,
    TicketParticipantResponse,
    TicketPropertyUpdateRequest,
    TicketResponse,
    TicketShareScopeUpdateRequest,
    TicketStatusUpdateRequest,
)
from app.services import notification_prefs, push
from app.services.access import active_contract_filter

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me/tickets", tags=["tickets"])
admin_router = APIRouter(prefix="/admin/tickets", tags=["tickets"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- shared helpers -----------------------------------------------------------


def _to_summary(t: Ticket) -> TicketResponse:
    return TicketResponse.model_validate(t)


def _contact_label(c: Contact) -> str:
    if c.kind == ContactKind.COMPANY and c.company_name:
        return c.company_name
    parts = [p for p in (c.first_name, c.last_name) if p]
    if parts:
        return " ".join(parts)
    return c.company_name or c.email or f"Kontakt {c.impower_id or c.id}"


def _format_address(p: Property | None) -> str | None:
    if p is None:
        return None
    street = " ".join(part for part in (p.street, p.number) if part).strip()
    zip_city = " ".join(part for part in (p.postal_code, p.city) if part).strip()
    combined = " · ".join(part for part in (street, zip_city) if part)
    return combined or None


async def _enrich_summaries(session: AsyncSession, tickets: list[Ticket]) -> list[TicketResponse]:
    """Batch-resolve property + creator details for a list of tickets.

    The SPA queue tile wants property name + address and the creator's
    name on every row; doing N joins per row would explode for any queue
    of more than a handful of items. Three batch queries (properties,
    users, contacts-by-impower-id) cover whatever set of tickets the
    caller passes in.
    """
    if not tickets:
        return []

    property_ids = {t.property_id for t in tickets if t.property_id}
    creator_ids = {t.created_by_user_id for t in tickets if t.created_by_user_id}

    properties: dict[uuid.UUID, Property] = {}
    if property_ids:
        prop_rows = (
            await session.scalars(select(Property).where(Property.id.in_(property_ids)))
        ).all()
        properties = {p.id: p for p in prop_rows}

    users: dict[uuid.UUID, User] = {}
    if creator_ids:
        user_rows = (await session.scalars(select(User).where(User.id.in_(creator_ids)))).all()
        users = {u.id: u for u in user_rows}

    impower_ids = {u.contact_id_impower for u in users.values() if u.contact_id_impower}
    contacts: dict[int, Contact] = {}
    if impower_ids:
        contact_rows = (
            await session.scalars(
                select(Contact).where(
                    Contact.impower_id.in_(impower_ids),
                    Contact.deleted_at.is_(None),
                )
            )
        ).all()
        contacts = {c.impower_id: c for c in contact_rows if c.impower_id is not None}

    out: list[TicketResponse] = []
    for t in tickets:
        prop = properties.get(t.property_id) if t.property_id else None
        creator = users.get(t.created_by_user_id) if t.created_by_user_id else None
        creator_contact = (
            contacts.get(creator.contact_id_impower)
            if creator and creator.contact_id_impower
            else None
        )
        out.append(
            TicketResponse(
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
                property_name=prop.name if prop else None,
                property_address=_format_address(prop),
                creator_email=creator.email if creator else None,
                creator_contact_label=_contact_label(creator_contact) if creator_contact else None,
                creator_contact_id_impower=creator_contact.impower_id if creator_contact else None,
                external_sender_email=t.external_sender_email,
            )
        )
    return out


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


async def _load_attachments_for_messages(
    session: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TicketMessageAttachment]]:
    """Batch-fetch all attachments for a set of message ids, indexed by
    message id. Returns an empty dict for the empty-input case so callers
    can blindly `attachments.get(m.id, [])` without a guard."""
    if not message_ids:
        return {}
    rows = (
        await session.scalars(
            select(TicketMessageAttachment)
            .where(TicketMessageAttachment.ticket_message_id.in_(message_ids))
            .order_by(TicketMessageAttachment.created_at)
        )
    ).all()
    out: dict[uuid.UUID, list[TicketMessageAttachment]] = {}
    for a in rows:
        out.setdefault(a.ticket_message_id, []).append(a)
    return out


async def _to_detail(
    t: Ticket, messages: list[TicketMessage], session: AsyncSession
) -> TicketDetailResponse:
    participants = await _load_participants(session, t.id)
    # Resolve author emails in one batch so the SPA can render thread rows
    # without N follow-up requests. Hard-deleted users → email is None.
    author_ids = {m.author_user_id for m in messages if m.author_user_id}
    author_emails: dict[uuid.UUID, str] = {}
    if author_ids:
        author_rows = (await session.scalars(select(User).where(User.id.in_(author_ids)))).all()
        author_emails = {u.id: u.email for u in author_rows}
    # Eager-load attachments for every message in one round-trip.
    attachments_by_msg = await _load_attachments_for_messages(session, [m.id for m in messages])
    message_resps = [
        TicketMessageResponse(
            id=m.id,
            ticket_id=m.ticket_id,
            author_user_id=m.author_user_id,
            author_email=(author_emails.get(m.author_user_id) if m.author_user_id else None),
            body=m.body,
            is_internal_note=m.is_internal_note,
            created_at=m.created_at,
            attachments=[
                TicketMessageAttachmentResponse.model_validate(a)
                for a in attachments_by_msg.get(m.id, [])
            ],
        )
        for m in messages
    ]
    # Reuse the same enrichment the queue uses so the detail response
    # carries property_name + address + creator_email — otherwise the
    # admin page falls back to a UUID prefix after assigning a property
    # to a previously-orphaned ticket from an unknown sender.
    enriched = (await _enrich_summaries(session, [t]))[0]
    return TicketDetailResponse(
        id=enriched.id,
        property_id=enriched.property_id,
        created_by_user_id=enriched.created_by_user_id,
        assignee_user_id=enriched.assignee_user_id,
        category=enriched.category,
        status=enriched.status,
        share_scope=enriched.share_scope,
        subject=enriched.subject,
        last_message_at=enriched.last_message_at,
        created_at=enriched.created_at,
        closed_at=enriched.closed_at,
        property_name=enriched.property_name,
        property_address=enriched.property_address,
        creator_email=enriched.creator_email,
        creator_contact_label=enriched.creator_contact_label,
        creator_contact_id_impower=enriched.creator_contact_id_impower,
        external_sender_email=enriched.external_sender_email,
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


def _attachments_for_resend(
    attachments: list[TicketMessageAttachment] | None,
) -> list[dict[str, str]]:
    """Convert TicketMessageAttachment rows into Resend's attachment
    format: `[{filename, content (base64)}]`.

    Reads each on-disk file at send time — we don't keep bytes in memory
    longer than the email request. Rows without a `local-disk:` prefix
    or with a missing file are skipped silently (the user already saw
    the upload succeed; we'd rather send the email without the
    attachment than fail the whole notification).
    """
    if not attachments:
        return []
    out: list[dict[str, str]] = []
    for att in attachments:
        if not att.storage_url or not att.storage_url.startswith("local-disk:"):
            continue
        suffix = att.storage_url[len("local-disk:") :]
        path = attachment_path(att.id, suffix)
        if not path.exists():
            logger.warning("Skipping attachment %s — file missing at %s", att.id, path)
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            logger.exception("Could not read attachment %s from disk", att.id)
            continue
        out.append(
            {
                "filename": att.filename,
                "content": base64.b64encode(raw).decode("ascii"),
            }
        )
    return out


async def _push_ticket_notification(
    session: AsyncSession,
    *,
    ticket: Ticket,
    recipients: list[str],
    sender_email: str,
    is_new_ticket: bool,
) -> None:
    """Mirror the email ticket-notification with a push to the same
    recipients who happen to be app users.

    The ticket notification path resolves recipients as bare email
    strings (it has to — external senders aren't users). We map the
    in-app subset back to User rows by email, minus the sender, and
    push to their devices. External-only recipients simply don't
    match a user row and get email only, which is correct.

    Best-effort: never raises into the caller's notification path.
    """
    targets = [e for e in recipients if e and e != sender_email]
    if not targets:
        return
    try:
        users = (
            await session.scalars(
                select(User).where(
                    User.email.in_(targets),
                    User.deleted_at.is_(None),
                )
            )
        ).all()
        if not users:
            return
        # Honour the TICKET push preference — drop users who turned it
        # off. (External, non-user recipients never reach here; they
        # only ever get email.)
        push_ids = await notification_prefs.filter_user_ids(
            session,
            user_ids=[u.id for u in users],
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.PUSH,
        )
        await push.notify_users(
            session,
            user_ids=push_ids,
            title="Neues Anliegen" if is_new_ticket else "Neue Antwort zu Ihrem Anliegen",
            body=ticket.subject,
            deep_link=f"whv://tickets/{ticket.id}",
            thread_id=f"ticket-{ticket.id}",
        )
    except Exception:
        logger.exception("ticket push fan-out failed for ticket=%s", ticket.id)


async def _filter_ticket_email_recipients(
    session: AsyncSession, recipients: list[str]
) -> list[str]:
    """Drop registered users who turned TICKET email off; keep external
    (non-user) addresses untouched — they have no account, so no
    preference, and must still receive the mail."""
    if not recipients:
        return recipients
    rows = (
        await session.execute(
            select(User.id, User.email).where(
                User.email.in_(recipients),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    email_to_id = {email: uid for uid, email in rows}
    if not email_to_id:
        return recipients
    ok_ids = set(
        await notification_prefs.filter_user_ids(
            session,
            user_ids=list(email_to_id.values()),
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.EMAIL,
        )
    )
    return [e for e in recipients if e not in email_to_id or email_to_id[e] in ok_ids]


async def _send_message_notification(
    *,
    email_client: EmailClient,
    ticket: Ticket,
    message: TicketMessage,
    recipients: list[str],
    sender_email: str,
    headers: dict[str, str] | None = None,
    message_attachments: list[TicketMessageAttachment] | None = None,
    is_new_ticket: bool = False,
    session: AsyncSession | None = None,
) -> tuple[str | None, str | None]:
    """Best-effort send — returns (message_id, error_string). Caller is
    responsible for capturing the outcome in audit if desired.

    Reply-To: when `settings.email_inbound_address` is set, every
    notification carries it so a recipient who hits "Reply" routes back
    to the SES inbound mailbox → /webhooks/email/inbound → posts as the
    next ticket message. That closes the email loop: the user (whether
    registered or external) never has to visit the portal to respond.
    The subject already carries `[#<short_id>]`, the inbound parser
    extracts the ref, and the message lands on the same ticket. Empty
    in dev so we don't direct staging replies into a void.
    """
    if not recipients:
        return None, "no recipients"
    # Push fan-out runs independently of the email outcome — a Resend
    # hiccup shouldn't suppress the push and vice versa. Only when a
    # session was threaded through (all in-request callers do).
    if session is not None:
        await _push_ticket_notification(
            session,
            ticket=ticket,
            recipients=recipients,
            sender_email=sender_email,
            is_new_ticket=is_new_ticket,
        )
        # Honour the TICKET email preference for registered recipients.
        # If everyone in-app opted out (and there's no external address
        # left), skip the email entirely — push already went out above.
        recipients = await _filter_ticket_email_recipients(session, recipients)
        if not recipients:
            return None, None
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
            is_new_ticket=is_new_ticket,
        )
        settings = get_settings()
        msg_id = await email_client.send(
            # Pass the list directly — Resend rejects a single
            # comma-joined string as 422 "Invalid `to` field".
            to=recipients,
            subject=subject,
            html=html,
            text=text,
            headers=headers,
            reply_to=settings.email_inbound_address or None,
            attachments=_attachments_for_resend(message_attachments) or None,
        )
        return msg_id, None
    except EmailError as exc:
        # Best-effort — caller doesn't block on failures, but a silent
        # failure on staging is exactly how a Verwalter ended up
        # missing new-ticket notifications. Log loud enough that the
        # next deploy smoke catches it.
        logger.warning(
            "ticket notification send failed: ticket=%s recipients=%s err=%s",
            ticket.id,
            recipients,
            exc,
        )
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
    rows = list((await session.scalars(stmt)).all())
    return await _enrich_summaries(session, rows)


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

    # Notify every Verwalter in the org that a new ticket was opened.
    # Best-effort — failure to send doesn't roll back the ticket
    # creation (logged via _send_message_notification). No participants
    # yet on a brand-new ticket, so we only fan out to Verwalter here.
    # `is_new_ticket=True` gives the email a "Neues Ticket: …" headline
    # so it's unambiguous in a busy inbox vs. reply notifications.
    recipients = await _verwalter_recipients(session, current_user.organization_id)
    # Exclude the creator from the recipient list so a Verwalter who
    # opens a test ticket from their own account doesn't see a copy
    # of their own message back. Real Eigentümer/Mieter creators aren't
    # Verwalter, so this is a no-op for them.
    recipients = [r for r in recipients if r != current_user.email]
    await _send_message_notification(
        email_client=email_client,
        ticket=ticket,
        message=first_message,
        recipients=recipients,
        sender_email=current_user.email,
        is_new_ticket=True,
        session=session,
    )

    await session.commit()
    await session.refresh(ticket)

    # KI-Antwortentwurf (interne Notiz) für Eigentümer-/Mieter-Tickets —
    # best-effort im Worker; ein Verwalter-eigenes Ticket braucht keinen.
    settings = get_settings()
    if (
        settings.rag_enabled
        and settings.ticket_ai_draft_enabled
        and current_user.role != UserRole.VERWALTER
    ):
        from app.workers.tasks import generate_ticket_ai_draft

        generate_ticket_ai_draft.delay(str(ticket.id))

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
    # SPA sets `defer_notification=True` when it's about to upload
    # attachments for this message — the notify email goes out via the
    # explicit POST .../{msg_id}/notify call once the uploads land, so
    # the recipient's mailbox actually carries the files. Legacy /
    # test callers leave the flag at its default False and get the
    # inline send.
    if not req.defer_notification:
        await _send_message_notification(
            email_client=email_client,
            ticket=ticket,
            message=message,
            recipients=recipients,
            sender_email=current_user.email,
            headers=await _latest_email_thread_headers(session, ticket.id),
            session=session,
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
    property_id: uuid.UUID | None = None,
) -> list[TicketResponse]:
    stmt = select(Ticket).where(Ticket.organization_id == current_user.organization_id)
    if status_filter is not None:
        stmt = stmt.where(Ticket.status == status_filter)
    if category is not None:
        stmt = stmt.where(Ticket.category == category)
    if property_id is not None:
        stmt = stmt.where(Ticket.property_id == property_id)
    stmt = stmt.order_by(Ticket.last_message_at.desc()).limit(200)
    rows = list((await session.scalars(stmt)).all())
    return await _enrich_summaries(session, rows)


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
    # When the SPA has attachments queued it sets `defer_notification=True`
    # so the email goes out via the explicit /notify endpoint after the
    # uploads land (so the email actually carries the files).
    if not req.is_internal_note and not req.defer_notification:
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
                session=session,
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


@admin_router.patch("/{ticket_id}/property", response_model=TicketResponse)
async def admin_set_ticket_property(
    ticket_id: uuid.UUID,
    req: TicketPropertyUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketResponse:
    """Assign or clear `tickets.property_id`.

    Primary use case: an inbound email arrives from a sender we don't
    have a registered user for. The webhook creates a ticket with
    external_sender_email set but property_id NULL — we don't know
    which Liegenschaft they're asking about. The Verwalter ties it to
    a property after triage so the ticket shows up in property-scoped
    views (queue filters, property-detail tab, PROPERTY share-scope).
    """
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    old_property_id = ticket.property_id

    if req.property_id is not None:
        # Same-org check — never let the Verwalter leak a ticket into
        # another organisation's property by id-fuzzing.
        prop = await session.scalar(
            select(Property).where(
                Property.id == req.property_id,
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
            )
        )
        if prop is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Property not found in organization",
            )

    ticket.property_id = req.property_id

    # If the scope is PROPERTY and we just cleared property_id, demote
    # back to PRIVATE so the access rule stays consistent (PROPERTY
    # scope requires a property to widen access against).
    if ticket.share_scope == TicketShareScope.PROPERTY and req.property_id is None:
        ticket.share_scope = TicketShareScope.PRIVATE

    if old_property_id != ticket.property_id:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="ticket_property_changed",
                target_type="tickets",
                target_id=str(ticket.id),
                payload_json={
                    "from": str(old_property_id) if old_property_id else None,
                    "to": str(ticket.property_id) if ticket.property_id else None,
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


async def _notify_property_share(
    session: AsyncSession, email_client: EmailClient, ticket: Ticket, actor: User
) -> None:
    """Best-effort fan-out after a ticket was widened to share_scope=PROPERTY
    ("alle Eigentümer des Objekts"): every member with an ACTIVE contract on
    the property — minus whoever flipped the switch — gets an email + push,
    honouring their TICKET preferences. Feedback: silently-shared tickets
    were simply never noticed."""
    if ticket.property_id is None:
        return
    try:
        users = (
            await session.scalars(
                select(User)
                .join(Contact, Contact.impower_id == User.contact_id_impower)
                .join(ContractContact, ContractContact.contact_id == Contact.id)
                .join(Contract, Contract.id == ContractContact.contract_id)
                .where(
                    User.organization_id == ticket.organization_id,
                    User.deleted_at.is_(None),
                    User.contact_id_impower.is_not(None),
                    User.role != UserRole.VERWALTER,
                    User.id != actor.id,
                    Contact.organization_id == ticket.organization_id,
                    Contract.property_id == ticket.property_id,
                    active_contract_filter(),
                )
                .distinct()
            )
        ).all()
        if not users:
            return
        user_ids = [u.id for u in users]
        email_ok = set(
            await notification_prefs.filter_user_ids(
                session,
                user_ids=user_ids,
                category=NotificationCategory.TICKET,
                channel=NotificationChannel.EMAIL,
            )
        )
        push_ids = await notification_prefs.filter_user_ids(
            session,
            user_ids=user_ids,
            category=NotificationCategory.TICKET,
            channel=NotificationChannel.PUSH,
        )
        prop = await session.get(Property, ticket.property_id)
        subject, html, text = render_ticket_shared_email(
            ticket_short_id=ticket.id.hex[:16],
            ticket_subject=ticket.subject,
            property_name=prop.name if prop else "—",
        )
        settings = get_settings()
        for u in users:
            if not u.email or u.id not in email_ok:
                continue
            try:
                await email_client.send(
                    to=u.email,
                    subject=subject,
                    html=html,
                    text=text,
                    reply_to=settings.email_inbound_address or None,
                )
            except EmailError:
                logger.warning("share email failed for %s (ticket=%s)", u.email, ticket.id)
        await push.notify_users(
            session,
            user_ids=push_ids,
            title="Anliegen freigegeben",
            body=ticket.subject,
            deep_link=f"whv://tickets/{ticket.id}",
            thread_id=f"ticket-{ticket.id}",
        )
    except Exception:
        logger.exception("property-share fan-out failed for ticket=%s", ticket.id)


# --- Owner-facing share-scope + participants ---------------------------------


@me_router.patch("/{ticket_id}/share-scope", response_model=TicketResponse)
async def update_my_share_scope(
    ticket_id: uuid.UUID,
    req: TicketShareScopeUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
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
    old_scope = ticket.share_scope
    ticket.share_scope = req.share_scope
    if old_scope != ticket.share_scope:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="ticket_share_scope_changed",
                target_type="tickets",
                target_id=str(ticket.id),
                payload_json={"from": old_scope.value, "to": ticket.share_scope.value},
            )
        )
    await session.commit()
    await session.refresh(ticket)
    # Publish moment: widening to "alle Eigentümer des Objekts" notifies the
    # property's members (email + push, TICKET preferences respected).
    if ticket.share_scope == TicketShareScope.PROPERTY and old_scope != TicketShareScope.PROPERTY:
        await _notify_property_share(session, email_client, ticket, current_user)
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
    email_client: Annotated[EmailClient, Depends(get_email_client)],
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
    old_scope = ticket.share_scope
    ticket.share_scope = req.share_scope
    if old_scope != ticket.share_scope:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="ticket_share_scope_changed",
                target_type="tickets",
                target_id=str(ticket.id),
                payload_json={"from": old_scope.value, "to": ticket.share_scope.value},
            )
        )
    await session.commit()
    await session.refresh(ticket)
    # Publish moment: widening to "alle Eigentümer des Objekts" notifies the
    # property's members (email + push, TICKET preferences respected).
    if ticket.share_scope == TicketShareScope.PROPERTY and old_scope != TicketShareScope.PROPERTY:
        await _notify_property_share(session, email_client, ticket, current_user)
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


# ── Attachments (Item 7) ──────────────────────────────────────────


async def _load_ticket_for_caller(
    *,
    session: AsyncSession,
    user: User,
    ticket_id: uuid.UUID,
    admin: bool,
) -> Ticket:
    """Fetch the ticket, asserting the caller can see it. Admin = trust
    the role check + org scope; portal callers go through `_owner_can_access`
    too. Same 404-on-no-access shape used elsewhere — we never leak
    existence of a ticket the caller can't read."""
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == user.organization_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if (
        not admin
        and user.role != UserRole.VERWALTER
        and not await _owner_can_access(session, user, ticket)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


async def _load_message_for_ticket(
    session: AsyncSession,
    *,
    message_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> TicketMessage:
    msg = await session.scalar(
        select(TicketMessage).where(
            TicketMessage.id == message_id,
            TicketMessage.ticket_id == ticket_id,
        )
    )
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return msg


async def _persist_attachment(
    *,
    session: AsyncSession,
    actor: User,
    ticket: Ticket,
    message: TicketMessage,
    settings: Settings,
    file: UploadFile,
) -> TicketMessageAttachment:
    """Shared upload pipeline used by both `/me` and `/admin` POSTs.

    Reads + validates the upload, writes the bytes to disk, persists the
    attachment row with a `local-disk:<suffix>` stamp on storage_url,
    writes an audit row. Caller is expected to have already validated
    that `actor` can write to this `ticket` (state check, etc.) — this
    helper deliberately stays narrow.
    """
    raw = await file.read()
    if len(raw) > settings.ticket_attachment_max_bytes:
        max_mb = settings.ticket_attachment_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Anhang darf höchstens {max_mb} MB groß sein.",
        )
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datei-Name fehlt.",
        )

    attachment = TicketMessageAttachment(
        ticket_message_id=message.id,
        filename=file.filename,
        mime_type=file.content_type,
        size_bytes=len(raw),
        storage_url="local-disk:.pending",  # rewritten after write
        uploaded_by_user_id=actor.id,
    )
    session.add(attachment)
    await session.flush()  # need the id before we can pick a file path

    try:
        _, suffix = write_attachment(attachment.id, file.filename, raw)
    except TicketAttachmentStorageError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Datei: {exc}",
        ) from exc

    attachment.storage_url = f"local-disk:{suffix}"
    session.add(
        AuditLog(
            organization_id=ticket.organization_id,
            actor_user_id=actor.id,
            action="ticket_attachment_uploaded",
            target_type="ticket_message_attachments",
            target_id=str(attachment.id),
            payload_json={
                "ticket_id": str(ticket.id),
                "ticket_message_id": str(message.id),
                "filename": attachment.filename,
                "size_bytes": attachment.size_bytes,
                "mime_type": attachment.mime_type,
            },
        )
    )
    await session.commit()
    await session.refresh(attachment)
    return attachment


@me_router.post(
    "/{ticket_id}/messages/{message_id}/attachments",
    response_model=TicketMessageAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_my_attachment(
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> TicketMessageAttachmentResponse:
    """Portal user attaches a file to a message they just posted.

    Scope check matches `/me/tickets/{id}` — caller must own / participate
    in the ticket. Doesn't gate on authorship of the *message* (we trust
    the typical flow of "post message, then upload its attachments" and
    don't want to break the legitimate "send a forgotten doc" use case
    where the user adds a file to their own earlier reply).
    """
    ticket = await _load_ticket_for_caller(
        session=session, user=current_user, ticket_id=ticket_id, admin=False
    )
    msg = await _load_message_for_ticket(session, message_id=message_id, ticket_id=ticket.id)
    # Non-Verwalter never see internal notes via /me, so they shouldn't
    # be able to upload to them either — pretend they don't exist.
    if msg.is_internal_note and current_user.role != UserRole.VERWALTER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    attachment = await _persist_attachment(
        session=session,
        actor=current_user,
        ticket=ticket,
        message=msg,
        settings=settings,
        file=file,
    )
    return TicketMessageAttachmentResponse.model_validate(attachment)


@admin_router.post(
    "/{ticket_id}/messages/{message_id}/attachments",
    response_model=TicketMessageAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_admin_attachment(
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> TicketMessageAttachmentResponse:
    ticket = await _load_ticket_for_caller(
        session=session, user=current_user, ticket_id=ticket_id, admin=True
    )
    msg = await _load_message_for_ticket(session, message_id=message_id, ticket_id=ticket.id)
    attachment = await _persist_attachment(
        session=session,
        actor=current_user,
        ticket=ticket,
        message=msg,
        settings=settings,
        file=file,
    )
    return TicketMessageAttachmentResponse.model_validate(attachment)


async def _resolve_attachment_for_download(
    *,
    session: AsyncSession,
    user: User,
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    admin: bool,
) -> tuple[TicketMessageAttachment, TicketMessage]:
    """Shared resolver for the GET download endpoints. Re-checks scope on
    every request — UUIDv7 IDs aren't a secret strong enough for
    invoice scans + photo evidence, so we always require auth + access."""
    ticket = await _load_ticket_for_caller(
        session=session, user=user, ticket_id=ticket_id, admin=admin
    )
    attachment = await session.scalar(
        select(TicketMessageAttachment)
        .join(
            TicketMessage,
            TicketMessage.id == TicketMessageAttachment.ticket_message_id,
        )
        .where(
            TicketMessageAttachment.id == attachment_id,
            TicketMessage.ticket_id == ticket.id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    msg = await _load_message_for_ticket(
        session, message_id=attachment.ticket_message_id, ticket_id=ticket.id
    )
    # Hide attachments on internal notes from non-Verwalter — same rule
    # as the message list filter.
    if msg.is_internal_note and not admin and user.role != UserRole.VERWALTER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return attachment, msg


def _attachment_file_response(
    attachment: TicketMessageAttachment,
) -> FileResponse:
    """Stream the bytes off disk. Raises 404 when the on-disk file is
    missing (admin deleted it from /var/lib by hand, or a half-failed
    upload left the DB row without a body)."""
    if not attachment.storage_url.startswith("local-disk:"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei ist nicht lokal hinterlegt.",
        )
    suffix = attachment.storage_url[len("local-disk:") :]
    path = attachment_path(attachment.id, suffix)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei wurde nicht gefunden.",
        )
    return FileResponse(
        path,
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.filename,
    )


@me_router.get("/{ticket_id}/attachments/{attachment_id}/file")
async def download_my_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    attachment, _ = await _resolve_attachment_for_download(
        session=session,
        user=current_user,
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        admin=False,
    )
    return _attachment_file_response(attachment)


@admin_router.get("/{ticket_id}/attachments/{attachment_id}/file")
async def download_admin_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    attachment, _ = await _resolve_attachment_for_download(
        session=session,
        user=current_user,
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        admin=True,
    )
    return _attachment_file_response(attachment)


@me_router.delete(
    "/{ticket_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_my_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Portal users can remove an attachment they themselves uploaded.
    Anyone else's attachment is read-only from the /me/ side — they
    have to ask the Verwalter to do it via /admin."""
    attachment, _ = await _resolve_attachment_for_download(
        session=session,
        user=current_user,
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        admin=False,
    )
    if attachment.uploaded_by_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur eigene Anhänge können entfernt werden.",
        )
    suffix = (
        attachment.storage_url[len("local-disk:") :]
        if attachment.storage_url.startswith("local-disk:")
        else None
    )
    await session.delete(attachment)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="ticket_attachment_deleted",
            target_type="ticket_message_attachments",
            target_id=str(attachment.id),
            payload_json={"ticket_id": str(ticket_id)},
        )
    )
    await session.commit()
    if suffix is not None:
        delete_attachment(attachment.id, suffix)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _send_deferred_notification(
    *,
    session: AsyncSession,
    email_client: EmailClient,
    actor: User,
    ticket: Ticket,
    message: TicketMessage,
    admin: bool,
) -> None:
    """Build the recipient list for a deferred-notification call and
    send it with the message's attachments. Shared by `/me` + `/admin`
    /notify endpoints. Internal notes don't get email regardless of
    who triggered the notify call — same rule as the inline path.
    """
    if message.is_internal_note:
        return

    if admin:
        # Admin reply → notify creator (or external sender) + participants.
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
    else:
        # Owner reply → Verwalter + creator + external sender + participants,
        # minus the author themselves.
        creator = (
            await session.scalar(select(User).where(User.id == ticket.created_by_user_id))
            if ticket.created_by_user_id
            else None
        )
        recipients = _dedupe(
            [
                *(await _verwalter_recipients(session, ticket.organization_id)),
                *(await _participant_emails(session, ticket.id)),
                *([creator.email] if creator and creator.deleted_at is None else []),
                *([ticket.external_sender_email] if ticket.external_sender_email else []),
            ]
        )
        recipients = [e for e in recipients if e != actor.email]

    if not recipients:
        return

    # Eager-load attachments for this message — the very reason we
    # deferred the notification in the first place.
    attachments_by_msg = await _load_attachments_for_messages(session, [message.id])
    attachments = attachments_by_msg.get(message.id, [])

    await _send_message_notification(
        email_client=email_client,
        ticket=ticket,
        message=message,
        recipients=recipients,
        sender_email=actor.email,
        headers=await _latest_email_thread_headers(session, ticket.id),
        message_attachments=attachments,
        session=session,
    )


@me_router.post(
    "/{ticket_id}/messages/{message_id}/notify",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def notify_my_message(
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> Response:
    """SPA calls this after uploading attachments to a message that
    was created with `defer_notification=True`. Sends the notification
    email with the message's attachments included so the recipient's
    mailbox actually carries the files."""
    ticket = await _load_ticket_for_caller(
        session=session, user=current_user, ticket_id=ticket_id, admin=False
    )
    msg = await _load_message_for_ticket(session, message_id=message_id, ticket_id=ticket.id)
    await _send_deferred_notification(
        session=session,
        email_client=email_client,
        actor=current_user,
        ticket=ticket,
        message=msg,
        admin=False,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post(
    "/{ticket_id}/messages/{message_id}/notify",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def notify_admin_message(
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> Response:
    ticket = await _load_ticket_for_caller(
        session=session, user=current_user, ticket_id=ticket_id, admin=True
    )
    msg = await _load_message_for_ticket(session, message_id=message_id, ticket_id=ticket.id)
    await _send_deferred_notification(
        session=session,
        email_client=email_client,
        actor=current_user,
        ticket=ticket,
        message=msg,
        admin=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.delete(
    "/{ticket_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_admin_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Verwalter can remove any attachment in their org."""
    attachment, _ = await _resolve_attachment_for_download(
        session=session,
        user=current_user,
        ticket_id=ticket_id,
        attachment_id=attachment_id,
        admin=True,
    )
    suffix = (
        attachment.storage_url[len("local-disk:") :]
        if attachment.storage_url.startswith("local-disk:")
        else None
    )
    await session.delete(attachment)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="ticket_attachment_deleted",
            target_type="ticket_message_attachments",
            target_id=str(attachment.id),
            payload_json={"ticket_id": str(ticket_id)},
        )
    )
    await session.commit()
    if suffix is not None:
        delete_attachment(attachment.id, suffix)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
