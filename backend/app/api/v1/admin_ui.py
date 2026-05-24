from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    Contract,
    InviteCode,
    Property,
    Unit,
    User,
    UserRole,
)

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


# --- Exception → redirect glue ------------------------------------------------
# The handler is registered in app/main.py since it's app-level. Exporting the
# exception keeps this router self-contained otherwise.
__all__ = ["NeedsLoginRedirect", "router"]
