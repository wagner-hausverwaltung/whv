from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.bootstrap import generate_invite_code
from app.auth.dependencies import require_role
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.invites import render_invite_email
from app.models import (
    AuditLog,
    CircularResolution,
    Contact,
    Contract,
    InviteCode,
    Property,
    ResolutionStatus,
    Ticket,
    TicketStatus,
    Unit,
    User,
    UserRole,
)
from app.schemas.admin import (
    AdminDashboardStats,
    AdminInviteResponse,
    CreateInviteRequest,
    InviteStatus,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Only Verwalter may touch admin endpoints. We pass it as a dep via Depends(_)
# from each handler — FastAPI builds the dependency graph correctly.
_verwalter_only = require_role(UserRole.VERWALTER)


def _status_for(invite: InviteCode, now: datetime) -> InviteStatus:
    if invite.consumed_at is not None:
        return InviteStatus.CONSUMED
    if invite.expires_at <= now:
        return InviteStatus.EXPIRED
    return InviteStatus.PENDING


def _to_response(
    invite: InviteCode,
    now: datetime,
    email_message_id: str | None = None,
) -> AdminInviteResponse:
    return AdminInviteResponse(
        code=invite.code,
        email=invite.email,
        role=invite.role,
        contact_id_impower=invite.contact_id_impower,
        scope_json=invite.scope_json,
        expires_at=invite.expires_at,
        consumed_at=invite.consumed_at,
        created_by=invite.created_by,
        created_at=invite.created_at,
        status=_status_for(invite, now),
        email_message_id=email_message_id,
    )


@router.post(
    "/invites",
    response_model=AdminInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    req: CreateInviteRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> AdminInviteResponse:
    """Verwalter creates a new invite. Email is sent best-effort: if the send
    fails, the invite row is still created and can be resent by re-issuing.
    """
    now = datetime.now(UTC)
    code = generate_invite_code()
    expires_at = now + timedelta(days=req.ttl_days)
    invite = InviteCode(
        organization_id=current_user.organization_id,
        code=code,
        email=req.email.lower(),
        contact_id_impower=req.contact_id_impower,
        role=req.role,
        scope_json=req.scope_json,
        expires_at=expires_at,
        created_by=current_user.id,
    )
    session.add(invite)
    await session.flush()

    email_message_id: str | None = None
    email_error: str | None = None
    try:
        subject, html, text = render_invite_email(req.email, code, req.role.value)
        email_message_id = await email_client.send(
            to=req.email, subject=subject, html=html, text=text
        )
    except EmailError as exc:
        email_error = str(exc)

    audit_payload: dict[str, Any] = {
        "email": req.email,
        "role": req.role.value,
        "ttl_days": req.ttl_days,
        "email_sent": email_message_id is not None,
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

    return _to_response(invite, now, email_message_id=email_message_id)


@router.get("/invites", response_model=list[AdminInviteResponse])
async def list_invites(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        InviteStatus | None,
        Query(alias="status", description="Filter to pending / consumed / expired"),
    ] = None,
) -> list[AdminInviteResponse]:
    now = datetime.now(UTC)
    stmt = select(InviteCode).where(InviteCode.organization_id == current_user.organization_id)
    if status_filter == InviteStatus.PENDING:
        stmt = stmt.where(InviteCode.consumed_at.is_(None), InviteCode.expires_at > now)
    elif status_filter == InviteStatus.CONSUMED:
        stmt = stmt.where(InviteCode.consumed_at.is_not(None))
    elif status_filter == InviteStatus.EXPIRED:
        stmt = stmt.where(InviteCode.consumed_at.is_(None), InviteCode.expires_at <= now)
    stmt = stmt.order_by(InviteCode.created_at.desc())
    rows = (await session.scalars(stmt)).all()
    return [_to_response(r, now) for r in rows]


@router.delete("/invites/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    code: str,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Mark a pending invite consumed (= no longer redeemable).

    Consumed/expired invites can't be revoked — they're already non-redeemable.
    """
    invite = await session.scalar(
        select(InviteCode).where(
            InviteCode.code == code,
            InviteCode.organization_id == current_user.organization_id,
        )
    )
    if invite is None or invite.consumed_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    now = datetime.now(UTC)
    invite.consumed_at = now
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="invite_revoked",
            target_type="invite_codes",
            target_id=code,
            payload_json={"email": invite.email},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _scalar_count(session: AsyncSession, stmt: Any) -> int:
    result = await session.scalar(stmt)
    return int(result or 0)


@router.get("/dashboard-stats", response_model=AdminDashboardStats)
async def dashboard_stats(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminDashboardStats:
    """Aggregate counts for the admin SPA dashboard.

    Same data as the Jinja /admin-ui/ dashboard, exposed as JSON so the
    React admin can render the same stats without server-side templating.
    """
    org_id = current_user.organization_id
    now = datetime.now(UTC)
    return AdminDashboardStats(
        pending_invites=await _scalar_count(
            session,
            select(func.count())
            .select_from(InviteCode)
            .where(
                InviteCode.organization_id == org_id,
                InviteCode.consumed_at.is_(None),
                InviteCode.expires_at > now,
            ),
        ),
        consumed_invites=await _scalar_count(
            session,
            select(func.count())
            .select_from(InviteCode)
            .where(
                InviteCode.organization_id == org_id,
                InviteCode.consumed_at.is_not(None),
            ),
        ),
        properties=await _scalar_count(
            session,
            select(func.count())
            .select_from(Property)
            .where(
                Property.organization_id == org_id,
                Property.deleted_at.is_(None),
            ),
        ),
        units=await _scalar_count(
            session,
            select(func.count())
            .select_from(Unit)
            .where(
                Unit.organization_id == org_id,
                Unit.deleted_at.is_(None),
            ),
        ),
        contracts=await _scalar_count(
            session,
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.organization_id == org_id,
                Contract.deleted_at.is_(None),
            ),
        ),
        contacts=await _scalar_count(
            session,
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.organization_id == org_id,
                Contact.deleted_at.is_(None),
            ),
        ),
        open_tickets=await _scalar_count(
            session,
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.organization_id == org_id,
                Ticket.status != TicketStatus.GESCHLOSSEN,
            ),
        ),
        open_resolutions=await _scalar_count(
            session,
            select(func.count())
            .select_from(CircularResolution)
            .where(
                CircularResolution.organization_id == org_id,
                CircularResolution.status == ResolutionStatus.OFFEN,
            ),
        ),
    )
