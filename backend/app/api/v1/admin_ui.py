import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import forgot_password as forgot_password_json
from app.api.v1.auth import reset_password as reset_password_json
from app.auth.bootstrap import generate_invite_code
from app.auth.dependencies import (
    ADMIN_COOKIE_NAME,
    NeedsLoginRedirect,
    get_admin_user_from_cookie,
)
from app.auth.jwt import encode_access_token
from app.auth.passwords import hash_password, verify_password
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.invites import render_invite_email
from app.models import (
    AuditLog,
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    InviteCode,
    Property,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketParticipant,
    TicketShareScope,
    TicketStatus,
    Unit,
    User,
    UserRole,
)
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest

router = APIRouter(prefix="/admin-ui", tags=["admin-ui"])

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# --- Login + logout -----------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "admin/login.html", {"current_user": None, "error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    auth_failed = False
    if user is None or user.deleted_at is not None or user.password_hash is None:
        hash_password("__dummy__")  # constant-ish timing
        auth_failed = True
    elif not verify_password(password, user.password_hash) or user.role != UserRole.VERWALTER:
        auth_failed = True

    if auth_failed or user is None:
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "current_user": None,
                "error": "Ungültige E-Mail-Adresse oder Passwort, oder fehlende Berechtigung.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user.last_login_at = datetime.now(UTC)
    access_token, _exp = encode_access_token(
        settings, user.id, user.role.value, user.organization_id
    )
    await session.commit()

    response = RedirectResponse("/admin-ui/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
        httponly=True,
        secure=settings.app_env != "dev",
        samesite="strict",
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    response = RedirectResponse("/admin-ui/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return response


# --- Forgot + reset password --------------------------------------------------
# These are pre-auth UI wrappers around the JSON /auth/forgot-password and
# /auth/reset-password handlers. We call those handlers directly (FastAPI route
# functions are just async callables) so the business logic stays in one place.


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/forgot_password.html",
        {"current_user": None, "error": None, "submitted": False},
    )


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    email: Annotated[str, Form()],
) -> Response:
    # Call the JSON handler directly — same no-enumeration behaviour, same
    # token issuance, same email send. We always render the "submitted" page
    # regardless of whether the email matched a user.
    await forgot_password_json(
        req=ForgotPasswordRequest(email=email),
        session=session,
        settings=settings,
        email_client=email_client,
    )
    return templates.TemplateResponse(
        request,
        "admin/forgot_password.html",
        {"current_user": None, "error": None, "submitted": True},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request, token: str = "") -> HTMLResponse:
    if not token:
        return templates.TemplateResponse(
            request,
            "admin/reset_password.html",
            {"current_user": None, "error": "Kein Token in der URL.", "token": ""},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return templates.TemplateResponse(
        request,
        "admin/reset_password.html",
        {"current_user": None, "error": None, "token": token},
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    try:
        await reset_password_json(
            req=ResetPasswordRequest(token=token, new_password=password),
            session=session,
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "admin/reset_password.html",
            {
                "current_user": None,
                "error": (
                    "Token ungültig, abgelaufen oder bereits eingelöst. "
                    "Bitte fordern Sie einen neuen an."
                    if exc.status_code == status.HTTP_400_BAD_REQUEST
                    else f"Unerwarteter Fehler: {exc.detail}"
                ),
                "token": token,
            },
            status_code=exc.status_code,
        )

    # Success — redirect to login with a flash query param.
    return RedirectResponse(
        "/admin-ui/login?reset=ok",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Dashboard ----------------------------------------------------------------


async def _scalar_count(session: AsyncSession, stmt: Any) -> int:
    result = await session.scalar(stmt)
    return int(result or 0)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    now = datetime.now(UTC)
    counts = {
        "pending_invites": await _scalar_count(
            session,
            select(func.count())
            .select_from(InviteCode)
            .where(
                InviteCode.organization_id == current_user.organization_id,
                InviteCode.consumed_at.is_(None),
                InviteCode.expires_at > now,
            ),
        ),
        "consumed_invites": await _scalar_count(
            session,
            select(func.count())
            .select_from(InviteCode)
            .where(
                InviteCode.organization_id == current_user.organization_id,
                InviteCode.consumed_at.is_not(None),
            ),
        ),
        "properties": await _scalar_count(
            session,
            select(func.count())
            .select_from(Property)
            .where(
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
            ),
        ),
        "units": await _scalar_count(
            session,
            select(func.count())
            .select_from(Unit)
            .where(
                Unit.organization_id == current_user.organization_id,
                Unit.deleted_at.is_(None),
            ),
        ),
        "contracts": await _scalar_count(
            session,
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.organization_id == current_user.organization_id,
                Contract.deleted_at.is_(None),
            ),
        ),
        "contacts": await _scalar_count(
            session,
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.organization_id == current_user.organization_id,
                Contact.deleted_at.is_(None),
            ),
        ),
    }
    return templates.TemplateResponse(
        request, "admin/dashboard.html", {"current_user": current_user, "counts": counts}
    )


# --- Invites ------------------------------------------------------------------


def _status_for(invite: InviteCode, now: datetime) -> str:
    if invite.consumed_at is not None:
        return "consumed"
    if invite.expires_at <= now:
        return "expired"
    return "pending"


@router.get("/invites", response_class=HTMLResponse)
async def invites_list(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: str | None = None,
) -> HTMLResponse:
    now = datetime.now(UTC)
    stmt = select(InviteCode).where(InviteCode.organization_id == current_user.organization_id)
    if status_filter == "pending":
        stmt = stmt.where(InviteCode.consumed_at.is_(None), InviteCode.expires_at > now)
    elif status_filter == "consumed":
        stmt = stmt.where(InviteCode.consumed_at.is_not(None))
    elif status_filter == "expired":
        stmt = stmt.where(InviteCode.consumed_at.is_(None), InviteCode.expires_at <= now)
    stmt = stmt.order_by(InviteCode.created_at.desc()).limit(200)
    rows = (await session.scalars(stmt)).all()
    invites = [(r, _status_for(r, now)) for r in rows]

    return templates.TemplateResponse(
        request,
        "admin/invites_list.html",
        {
            "current_user": current_user,
            "invites": invites,
            "status_filter": status_filter,
            "roles": [r.value for r in UserRole],
        },
    )


@router.get("/invites/new", response_class=HTMLResponse)
async def invite_new_form(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/invites_new.html",
        {
            "current_user": current_user,
            "roles": [r.value for r in UserRole],
            "error": None,
        },
    )


@router.post("/invites/new")
async def invite_new_submit(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    email: Annotated[str, Form()],
    role: Annotated[str, Form()],
    contact_id_impower: Annotated[str, Form()] = "",
    ttl_days: Annotated[int, Form()] = 14,
) -> Response:
    try:
        role_enum = UserRole(role)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "admin/invites_new.html",
            {
                "current_user": current_user,
                "roles": [r.value for r in UserRole],
                "error": f"Ungültige Rolle: {role}",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    contact_id_int: int | None = None
    if contact_id_impower.strip():
        try:
            contact_id_int = int(contact_id_impower.strip())
        except ValueError:
            return templates.TemplateResponse(
                request,
                "admin/invites_new.html",
                {
                    "current_user": current_user,
                    "roles": [r.value for r in UserRole],
                    "error": "Impower-Contact-ID muss eine ganze Zahl sein.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    now = datetime.now(UTC)
    code = generate_invite_code()
    invite = InviteCode(
        organization_id=current_user.organization_id,
        code=code,
        email=email.strip().lower(),
        contact_id_impower=contact_id_int,
        role=role_enum,
        expires_at=now + timedelta(days=ttl_days),
        created_by=current_user.id,
    )
    session.add(invite)
    await session.flush()

    email_message_id: str | None = None
    email_error: str | None = None
    try:
        subject, html, text = render_invite_email(invite.email, code, role_enum.value)
        email_message_id = await email_client.send(
            to=invite.email, subject=subject, html=html, text=text
        )
    except EmailError as exc:
        email_error = str(exc)

    audit_payload: dict[str, Any] = {
        "email": invite.email,
        "role": role_enum.value,
        "ttl_days": ttl_days,
        "email_sent": email_message_id is not None,
        "via": "admin_ui",
    }
    if email_error is not None:
        audit_payload["email_error"] = email_error[:200]
    if email_message_id is not None:
        audit_payload["email_message_id"] = email_message_id

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="invite_created",
            target_type="invite_codes",
            target_id=code,
            payload_json=audit_payload,
        )
    )
    await session.commit()

    return RedirectResponse(
        f"/admin-ui/invites?status=pending&created={code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/invites/{code}/revoke")
async def invite_revoke(
    code: str,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    invite = await session.scalar(
        select(InviteCode).where(
            InviteCode.code == code,
            InviteCode.organization_id == current_user.organization_id,
        )
    )
    if invite is not None and invite.consumed_at is None:
        invite.consumed_at = datetime.now(UTC)
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="invite_revoked",
                target_type="invite_codes",
                target_id=code,
                payload_json={"email": invite.email, "via": "admin_ui"},
            )
        )
        await session.commit()
    return RedirectResponse("/admin-ui/invites", status_code=status.HTTP_303_SEE_OTHER)


# --- Audit log ----------------------------------------------------------------


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == current_user.organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {"current_user": current_user, "rows": rows},
    )


# --- Pickers for the invite form (HTMX fragments) -----------------------------
# These return small HTML fragments rather than full pages — the invite form
# uses HTMX to fetch them as the user types, and a sprinkle of inline JS to
# capture clicks and populate hidden inputs.


def _contact_display_name(c: Contact) -> str:
    """Single-line display label for a contact in the picker."""
    if c.kind == ContactKind.COMPANY and c.company_name:
        return c.company_name
    parts = [p for p in (c.first_name, c.last_name) if p]
    if parts:
        return " ".join(parts)
    return c.company_name or c.email or f"Kontakt {c.impower_id or c.id}"


@router.get("/properties/search", response_class=HTMLResponse)
async def properties_search(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = "",
) -> HTMLResponse:
    """HTMX fragment: matching properties for the invite form picker."""
    q_stripped = q.strip()
    if len(q_stripped) < 2:
        # Avoid flooding the UI on a single keystroke
        return templates.TemplateResponse(
            request,
            "admin/_picker_results.html",
            {"results": [], "q": q_stripped, "kind": "property", "hint_min_chars": 2},
        )

    like = f"%{q_stripped}%"
    rows = (
        await session.scalars(
            select(Property)
            .where(
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
                (
                    Property.name.ilike(like)
                    | Property.property_hr_id.ilike(like)
                    | Property.city.ilike(like)
                    | Property.street.ilike(like)
                ),
            )
            .order_by(Property.name)
            .limit(20)
        )
    ).all()

    results = [
        {
            "id": str(p.id),
            "label": p.name,
            "detail": " · ".join(
                bit
                for bit in (
                    p.property_hr_id,
                    p.city,
                    p.street,
                )
                if bit
            ),
        }
        for p in rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/_picker_results.html",
        {"results": results, "q": q_stripped, "kind": "property"},
    )


@router.get(
    "/properties/{property_uuid}/contacts/search",
    response_class=HTMLResponse,
)
async def property_contacts_search(
    request: Request,
    property_uuid: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = "",
) -> HTMLResponse:
    """HTMX fragment: contacts linked to `property_uuid` via contract_contacts."""
    # Verify the property exists in this org first (silent fallback to empty
    # results on mismatch — avoids leaking property existence across orgs).
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_uuid,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        return templates.TemplateResponse(
            request,
            "admin/_picker_results.html",
            {"results": [], "q": q.strip(), "kind": "contact"},
        )

    q_stripped = q.strip()
    base_stmt = (
        select(Contact)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
            Contact.impower_id.is_not(None),  # picker only useful if we have an Impower ID
            Contract.property_id == property_uuid,
            Contract.deleted_at.is_(None),
        )
        .distinct()
    )
    if q_stripped:
        like = f"%{q_stripped}%"
        base_stmt = base_stmt.where(
            Contact.first_name.ilike(like)
            | Contact.last_name.ilike(like)
            | Contact.company_name.ilike(like)
            | Contact.email.ilike(like)
        )

    rows = (await session.scalars(base_stmt.order_by(Contact.last_name).limit(20))).all()

    results = [
        {
            "id": str(c.impower_id),  # what the invite form actually wants
            "label": _contact_display_name(c),
            "email": c.email or "",  # surfaced via data-email; "" → JS swaps hint
            "detail": " · ".join(
                bit
                for bit in (
                    c.kind.value,
                    c.email,
                    c.city,
                )
                if bit
            ),
        }
        for c in rows
    ]
    return templates.TemplateResponse(
        request,
        "admin/_picker_results.html",
        {"results": results, "q": q_stripped, "kind": "contact"},
    )


# --- Tickets (Verwalter queue + thread) ---------------------------------------


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_list(
    request: Request,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: str | None = None,
    category_filter: str | None = None,
) -> HTMLResponse:
    import contextlib

    stmt = select(Ticket).where(Ticket.organization_id == current_user.organization_id)
    if status_filter:
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Ticket.status == TicketStatus(status_filter))
    if category_filter:
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Ticket.category == TicketCategory(category_filter))
    stmt = stmt.order_by(Ticket.last_message_at.desc()).limit(200)
    rows = (await session.scalars(stmt)).all()
    return templates.TemplateResponse(
        request,
        "admin/tickets_list.html",
        {
            "current_user": current_user,
            "tickets": rows,
            "status_filter": status_filter,
            "category_filter": category_filter,
            "statuses": [s.value for s in TicketStatus],
            "categories": [c.value for c in TicketCategory],
        },
    )


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request,
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == current_user.organization_id,
        )
    )
    if ticket is None:
        return templates.TemplateResponse(
            request,
            "admin/tickets_detail.html",
            {
                "current_user": current_user,
                "ticket": None,
                "messages": [],
                "error": "Ticket nicht gefunden.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    messages = list(
        (
            await session.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket.id)
                .order_by(TicketMessage.created_at)
            )
        ).all()
    )

    # Resolve author emails for display
    author_ids = {m.author_user_id for m in messages}
    author_emails: dict[uuid.UUID, str] = {}
    if author_ids:
        author_rows = (await session.scalars(select(User).where(User.id.in_(author_ids)))).all()
        author_emails = {u.id: u.email for u in author_rows}

    # Participants (explicit named) — join to User for the email display.
    participant_rows = (
        await session.execute(
            select(TicketParticipant, User.email)
            .join(User, User.id == TicketParticipant.user_id)
            .where(TicketParticipant.ticket_id == ticket.id)
            .order_by(TicketParticipant.added_at)
        )
    ).all()
    participants = [
        {"user_id": p.user_id, "email": email, "added_at": p.added_at}
        for p, email in participant_rows
    ]

    return templates.TemplateResponse(
        request,
        "admin/tickets_detail.html",
        {
            "current_user": current_user,
            "ticket": ticket,
            "messages": messages,
            "author_emails": author_emails,
            "participants": participants,
            "statuses": [s.value for s in TicketStatus],
            "share_scopes": [s.value for s in TicketShareScope],
            "error": None,
        },
    )


@router.post("/tickets/{ticket_id}/reply")
async def ticket_reply_submit(
    request: Request,
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    body: Annotated[str, Form()],
    is_internal_note: Annotated[str, Form()] = "",
) -> Response:
    from app.api.v1.tickets import post_admin_message
    from app.schemas.ticket import TicketMessageCreateRequest

    req = TicketMessageCreateRequest(
        body=body,
        is_internal_note=bool(is_internal_note),
    )
    await post_admin_message(
        ticket_id=ticket_id,
        req=req,
        current_user=current_user,
        session=session,
        email_client=email_client,
    )
    return RedirectResponse(
        f"/admin-ui/tickets/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tickets/{ticket_id}/status")
async def ticket_status_submit(
    request: Request,
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    new_status: Annotated[str, Form()],
) -> Response:
    from app.api.v1.tickets import patch_ticket
    from app.schemas.ticket import TicketStatusUpdateRequest

    try:
        status_enum = TicketStatus(new_status)
    except ValueError:
        return RedirectResponse(
            f"/admin-ui/tickets/{ticket_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    await patch_ticket(
        ticket_id=ticket_id,
        req=TicketStatusUpdateRequest(status=status_enum),
        current_user=current_user,
        session=session,
    )
    return RedirectResponse(
        f"/admin-ui/tickets/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tickets/{ticket_id}/share-scope")
async def ticket_share_scope_submit(
    request: Request,
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    share_scope: Annotated[str, Form()],
) -> Response:
    import contextlib

    from app.api.v1.tickets import update_admin_share_scope
    from app.schemas.ticket import TicketShareScopeUpdateRequest

    with contextlib.suppress(ValueError, HTTPException):
        await update_admin_share_scope(
            ticket_id=ticket_id,
            req=TicketShareScopeUpdateRequest(share_scope=TicketShareScope(share_scope)),
            current_user=current_user,
            session=session,
        )
    return RedirectResponse(
        f"/admin-ui/tickets/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tickets/{ticket_id}/participants/add")
async def ticket_participant_add_submit(
    request: Request,
    ticket_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email: Annotated[str, Form()],
) -> Response:
    import contextlib

    from app.api.v1.tickets import add_admin_participant
    from app.schemas.ticket import TicketParticipantAddRequest

    # Swallow 404 (unknown email) etc. — Jinja UI doesn't surface inline errors
    # yet; user re-tries with a known email. Audit log captures the attempt.
    with contextlib.suppress(HTTPException):
        await add_admin_participant(
            ticket_id=ticket_id,
            req=TicketParticipantAddRequest(email=email),
            current_user=current_user,
            session=session,
        )
    return RedirectResponse(
        f"/admin-ui/tickets/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tickets/{ticket_id}/participants/{user_id}/remove")
async def ticket_participant_remove_submit(
    request: Request,
    ticket_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_admin_user_from_cookie)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    from app.api.v1.tickets import remove_admin_participant

    await remove_admin_participant(
        ticket_id=ticket_id,
        user_id=user_id,
        current_user=current_user,
        session=session,
    )
    return RedirectResponse(
        f"/admin-ui/tickets/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Exception → redirect glue ------------------------------------------------
# The handler is registered in app/main.py since it's app-level. Exporting the
# exception keeps this router self-contained otherwise.
__all__ = ["NeedsLoginRedirect", "router"]
