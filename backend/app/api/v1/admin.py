import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.bootstrap import generate_invite_code
from app.auth.dependencies import require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.invites import render_invite_email
from app.integrations.storage.property_images import (
    PropertyImageError,
    delete_property_image,
    write_property_image,
)
from app.models import (
    AuditLog,
    CircularResolution,
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    Document,
    DocumentKind,
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
    AdminAuditLogResponse,
    AdminContactListItem,
    AdminContactSearchResult,
    AdminContractListItem,
    AdminDashboardStats,
    AdminInviteResponse,
    AdminPropertyCompanyResponse,
    AdminPropertyDetailResponse,
    AdminPropertyListItem,
    AdminPropertySearchResult,
    AdminUnitListItem,
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

    Eight tiles powering the admin SPA dashboard at /admin: pending +
    consumed invites, master-data counts, open tickets + resolutions.
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


# --- Typeahead pickers (JSON) ------------------------------------------------
# JSON search endpoints for the admin SPA's MUI Autocomplete components.
# Capped to keep dropdowns sane.


def _contact_display_name(c: Contact) -> str:
    if c.kind == ContactKind.COMPANY and c.company_name:
        return c.company_name
    parts = [p for p in (c.first_name, c.last_name) if p]
    if parts:
        return " ".join(parts)
    return c.company_name or c.email or f"Kontakt {c.impower_id or c.id}"


@router.get("/properties/search", response_model=list[AdminPropertySearchResult])
async def properties_search(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = "",
) -> list[AdminPropertySearchResult]:
    q_stripped = q.strip()
    stmt = (
        select(Property)
        .where(
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
        .order_by(Property.name)
        .limit(25)
    )
    if q_stripped:
        like = f"%{q_stripped}%"
        stmt = stmt.where(
            Property.name.ilike(like)
            | Property.property_hr_id.ilike(like)
            | Property.city.ilike(like)
            | Property.street.ilike(like)
        )
    rows = (await session.scalars(stmt)).all()
    return [
        AdminPropertySearchResult(
            id=p.id,
            name=p.name,
            property_hr_id=p.property_hr_id,
            city=p.city,
            street=p.street,
        )
        for p in rows
    ]


@router.get(
    "/properties/{property_id}/contacts/search",
    response_model=list[AdminContactSearchResult],
)
async def property_contacts_search(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = "",
) -> list[AdminContactSearchResult]:
    """Contacts that hold a contract on the given property.

    Silent empty fallback on cross-org property IDs — avoids leaking
    existence across orgs while keeping the picker UX simple.
    """
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        return []

    q_stripped = q.strip()
    stmt = (
        select(Contact)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
            Contact.impower_id.is_not(None),  # picker requires Impower ID
            Contract.property_id == property_id,
            Contract.deleted_at.is_(None),
        )
        .order_by(Contact.last_name, Contact.company_name)
        .limit(25)
        .distinct()
    )
    if q_stripped:
        like = f"%{q_stripped}%"
        stmt = stmt.where(
            Contact.first_name.ilike(like)
            | Contact.last_name.ilike(like)
            | Contact.company_name.ilike(like)
            | Contact.email.ilike(like)
        )
    rows = (await session.scalars(stmt)).all()
    return [
        AdminContactSearchResult(
            impower_id=c.impower_id,
            label=_contact_display_name(c),
            email=c.email,
        )
        for c in rows
        if c.impower_id is not None
    ]


# --- Audit log (JSON) --------------------------------------------------------


@router.get("/audit-log", response_model=list[AdminAuditLogResponse])
async def list_audit_log(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminAuditLogResponse]:
    """Most recent audit-log rows for the caller's org, newest first.

    `actor_email` is resolved in one batch so the SPA renders the table
    without an N+1 lookup. Hard limit of 500 — past that the operator
    should query the database directly.
    """
    capped = max(1, min(limit, 500))
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == current_user.organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(capped)
        )
    ).all()

    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    emails: dict[uuid.UUID, str] = {}
    if actor_ids:
        users = (await session.scalars(select(User).where(User.id.in_(actor_ids)))).all()
        emails = {u.id: u.email for u in users}

    return [
        AdminAuditLogResponse(
            id=r.id,
            actor_user_id=r.actor_user_id,
            actor_email=emails.get(r.actor_user_id) if r.actor_user_id else None,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            payload_json=r.payload_json,
            created_at=r.created_at,
        )
        for r in rows
    ]


# --- Property detail + companies (admin property page) ----------------------


def _format_property_label(c: Contact) -> str:
    if c.kind == ContactKind.COMPANY and c.company_name:
        return c.company_name
    parts = [p for p in (c.first_name, c.last_name) if p]
    if parts:
        return " ".join(parts)
    return c.company_name or c.email or f"Kontakt {c.impower_id or c.id}"


@router.get("/properties/{property_id}", response_model=AdminPropertyDetailResponse)
async def admin_property_detail(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPropertyDetailResponse:
    """Admin property detail — master data + per-tab counts.

    Counts power the right-hand tab badges (e.g. "Tickets (3)") on the
    SPA property page; the tab content itself comes from the existing
    list endpoints filtered by ?property_id=.
    """
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    org_id = current_user.organization_id
    units_count = await _scalar_count(
        session,
        select(func.count())
        .select_from(Unit)
        .where(
            Unit.organization_id == org_id,
            Unit.property_id == property_id,
            Unit.deleted_at.is_(None),
        ),
    )
    contracts_count = await _scalar_count(
        session,
        select(func.count())
        .select_from(Contract)
        .where(
            Contract.organization_id == org_id,
            Contract.property_id == property_id,
            Contract.deleted_at.is_(None),
        ),
    )
    # Contacts linked to any contract on this property (distinct).
    contacts_count = await _scalar_count(
        session,
        select(func.count(func.distinct(ContractContact.contact_id)))
        .select_from(ContractContact)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            Contract.organization_id == org_id,
            Contract.property_id == property_id,
            Contract.deleted_at.is_(None),
        ),
    )
    open_tickets_count = await _scalar_count(
        session,
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.organization_id == org_id,
            Ticket.property_id == property_id,
            Ticket.status != TicketStatus.GESCHLOSSEN,
        ),
    )
    open_resolutions_count = await _scalar_count(
        session,
        select(func.count())
        .select_from(CircularResolution)
        .where(
            CircularResolution.organization_id == org_id,
            CircularResolution.property_id == property_id,
            CircularResolution.status == ResolutionStatus.OFFEN,
        ),
    )
    invoice_companies_count = await _scalar_count(
        session,
        select(func.count(func.distinct(Document.contact_id)))
        .select_from(Document)
        .where(
            Document.organization_id == org_id,
            Document.property_id == property_id,
            Document.kind == DocumentKind.RECHNUNG,
            Document.contact_id.is_not(None),
            Document.deleted_at.is_(None),
        ),
    )

    return AdminPropertyDetailResponse(
        id=prop.id,
        name=prop.name,
        impower_id=prop.impower_id,
        property_hr_id=prop.property_hr_id,
        type=prop.type.value,
        state=prop.state.value,
        city=prop.city,
        street=prop.street,
        number=prop.number,
        postal_code=prop.postal_code,
        country=prop.country,
        image_url=prop.image_url,
        units_count=units_count,
        contracts_count=contracts_count,
        contacts_count=contacts_count,
        open_tickets_count=open_tickets_count,
        open_resolutions_count=open_resolutions_count,
        invoice_companies_count=invoice_companies_count,
    )


@router.put("/properties/{property_id}/image", response_model=AdminPropertyDetailResponse)
async def upload_property_image(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> AdminPropertyDetailResponse:
    """Verwalter uploads (or replaces) a property hero photo.

    Pillow normalises any JPEG/PNG/WebP/GIF/BMP to a 1280x960 PNG. The
    URL stored on properties.image_url carries a cache-bust query so the
    SPA refetches when the photo changes.
    """
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    raw = await file.read()
    if len(raw) > settings.property_image_max_bytes:
        max_mb = settings.property_image_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Bild darf höchstens {max_mb} MB groß sein.",
        )
    try:
        url = write_property_image(prop.id, raw)
    except PropertyImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Bilddatei: {exc}",
        ) from exc

    prop.image_url = url
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="property_image_updated",
            target_type="properties",
            target_id=str(prop.id),
            payload_json={"size_bytes": len(raw)},
        )
    )
    await session.commit()
    # Re-fetch via the detail endpoint so the SPA gets the count fields
    # populated too — saves a follow-up request after upload.
    return await admin_property_detail(prop.id, current_user, session)


@router.delete("/properties/{property_id}/image", response_model=AdminPropertyDetailResponse)
async def remove_property_image(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPropertyDetailResponse:
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    delete_property_image(prop.id)
    prop.image_url = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="property_image_deleted",
            target_type="properties",
            target_id=str(prop.id),
            payload_json={},
        )
    )
    await session.commit()
    return await admin_property_detail(prop.id, current_user, session)


@router.get(
    "/properties/{property_id}/companies",
    response_model=list[AdminPropertyCompanyResponse],
)
async def admin_property_companies(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AdminPropertyCompanyResponse]:
    """Vendor companies billed against this property.

    For each distinct Contact that appears as documents.contact_id on a
    RECHNUNG-kind Document for the property, return aggregate stats:
    invoice count, sum of amounts, most-recent invoice date. Sorted by
    total spend descending so the bigger relationships float to the top.
    """
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    stmt = (
        select(
            Document.contact_id,
            func.count(Document.id).label("invoice_count"),
            func.sum(Document.amount).label("total_amount"),
            func.max(Document.issued_date).label("most_recent_date"),
        )
        .where(
            Document.organization_id == current_user.organization_id,
            Document.property_id == property_id,
            Document.kind == DocumentKind.RECHNUNG,
            Document.contact_id.is_not(None),
            Document.deleted_at.is_(None),
        )
        .group_by(Document.contact_id)
    )
    agg_rows = (await session.execute(stmt)).all()
    if not agg_rows:
        return []

    contact_ids = [r.contact_id for r in agg_rows]
    contact_lookup_rows = (
        await session.scalars(
            select(Contact).where(
                Contact.id.in_(contact_ids),
                Contact.deleted_at.is_(None),
            )
        )
    ).all()
    contacts = {c.id: c for c in contact_lookup_rows}

    out: list[AdminPropertyCompanyResponse] = []
    for row in agg_rows:
        c = contacts.get(row.contact_id)
        if c is None:
            continue  # Contact soft-deleted since invoice synced — skip.
        most_recent: datetime | None = None
        if row.most_recent_date is not None:
            # most_recent_date is a date — convert to datetime for the response.
            most_recent = datetime.combine(row.most_recent_date, datetime.min.time(), tzinfo=UTC)
        out.append(
            AdminPropertyCompanyResponse(
                contact_id=c.id,
                impower_id=c.impower_id,
                name=_format_property_label(c),
                email=c.email,
                phone=c.phone,
                invoice_count=int(row.invoice_count),
                total_amount=float(row.total_amount) if row.total_amount is not None else None,
                most_recent_invoice_at=most_recent,
            )
        )
    out.sort(key=lambda r: r.total_amount or 0, reverse=True)
    return out


# --- Stammdaten lists (drill-down from dashboard cards) ----------------------
# Each returns the first `limit` rows (capped at 1000) sorted alphabetically.
# They power the four SPA tabs Objekte / Einheiten / Verträge / Kontakte.


@router.get("/properties", response_model=list[AdminPropertyListItem])
async def list_properties(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminPropertyListItem]:
    capped = max(1, min(limit, 1000))
    rows = (
        await session.scalars(
            select(Property)
            .where(
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
            )
            .order_by(Property.name)
            .limit(capped)
        )
    ).all()
    return [
        AdminPropertyListItem(
            id=p.id,
            name=p.name,
            property_hr_id=p.property_hr_id,
            type=p.type.value,
            state=p.state.value,
            city=p.city,
            street=p.street,
            number=p.number,
            postal_code=p.postal_code,
            image_url=p.image_url,
        )
        for p in rows
    ]


@router.get("/units", response_model=list[AdminUnitListItem])
async def list_units(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminUnitListItem]:
    capped = max(1, min(limit, 1000))
    rows = (
        await session.execute(
            select(Unit, Property.name)
            .join(Property, Property.id == Unit.property_id)
            .where(
                Unit.organization_id == current_user.organization_id,
                Unit.deleted_at.is_(None),
            )
            .order_by(Property.name, Unit.unit_hr_id)
            .limit(capped)
        )
    ).all()
    return [
        AdminUnitListItem(
            id=u.id,
            unit_hr_id=u.unit_hr_id,
            type=u.type.value,
            floor=u.floor,
            position=u.position,
            area_m2=float(u.area_m2) if u.area_m2 is not None else None,
            property_id=u.property_id,
            property_name=pname,
        )
        for u, pname in rows
    ]


@router.get("/contracts", response_model=list[AdminContractListItem])
async def list_contracts(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminContractListItem]:
    capped = max(1, min(limit, 1000))
    rows = (
        await session.execute(
            select(Contract, Property.name)
            .join(Property, Property.id == Contract.property_id)
            .where(
                Contract.organization_id == current_user.organization_id,
                Contract.deleted_at.is_(None),
            )
            .order_by(Property.name, Contract.type, Contract.contract_number)
            .limit(capped)
        )
    ).all()
    return [
        AdminContractListItem(
            id=c.id,
            type=c.type.value,
            contract_number=c.contract_number,
            name=c.name,
            start_date=c.start_date,
            end_date=c.end_date,
            is_vacant=c.is_vacant,
            property_id=c.property_id,
            property_name=pname,
        )
        for c, pname in rows
    ]


@router.get("/contacts", response_model=list[AdminContactListItem])
async def list_contacts(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminContactListItem]:
    capped = max(1, min(limit, 1000))
    rows = (
        await session.scalars(
            select(Contact)
            .where(
                Contact.organization_id == current_user.organization_id,
                Contact.deleted_at.is_(None),
            )
            .order_by(Contact.last_name, Contact.company_name)
            .limit(capped)
        )
    ).all()
    return [
        AdminContactListItem(
            id=c.id,
            impower_id=c.impower_id,
            kind=c.kind.value,
            name=_format_property_label(c),
            email=c.email,
            phone=c.phone,
            city=c.city,
        )
        for c in rows
    ]
