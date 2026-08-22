import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.bootstrap import generate_invite_code
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.docuseal.client import DocuSealError, get_docuseal_client
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.invites import render_invite_email
from app.integrations.storage.documents import (
    DocumentStorageError,
    document_path,
    write_document,
)
from app.integrations.storage.documents import (
    delete_document as storage_delete_document,
)
from app.integrations.storage.property_images import (
    PropertyImageError,
    delete_property_image,
    property_image_path,
    write_property_image,
)
from app.models import (
    AssemblyStatus,
    AuditLog,
    CircularResolution,
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    ContractType,
    Document,
    DocumentFolder,
    DocumentKind,
    DocumentVisibility,
    EtvAssembly,
    InviteCode,
    OrganizationPropertySelection,
    Property,
    PropertyType,
    ResolutionStatus,
    SignatureRequest,
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
    AdminPropertyContactInviteInfo,
    AdminPropertyContactResponse,
    AdminPropertyDetailResponse,
    AdminPropertyListItem,
    AdminPropertySearchResult,
    AdminPropertySelectionResponse,
    AdminPropertySelectionUpdate,
    AdminUnitDistributionKeysUpdate,
    AdminUnitListItem,
    BulkInviteOutcome,
    BulkInviteOutcomeStatus,
    BulkInviteRequest,
    BulkInviteResponse,
    CreateInviteRequest,
    InviteStatus,
)
from app.schemas.document import (
    DocumentFolderCreateRequest,
    DocumentFolderResponse,
    DocumentFolderUpdateRequest,
    DocumentResponse,
    DocumentUpdateRequest,
)
from app.schemas.signature import SignatureRequestResponse
from app.services import signatures as signatures_svc

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
    org_id = current_user.organization_id
    rows = (
        await session.scalars(
            select(Property)
            .where(
                Property.organization_id == org_id,
                Property.deleted_at.is_(None),
            )
            .order_by(Property.name)
            .limit(capped)
        )
    ).all()
    property_ids = [p.id for p in rows]

    # Per-property unit counts (one grouped query, not N+1).
    unit_counts: dict[uuid.UUID, int] = {}
    if property_ids:
        unit_rows = await session.execute(
            select(Unit.property_id, func.count(Unit.id))
            .where(
                Unit.organization_id == org_id,
                Unit.deleted_at.is_(None),
                Unit.property_id.in_(property_ids),
            )
            .group_by(Unit.property_id)
        )
        unit_counts = {pid: int(n) for pid, n in unit_rows.all()}

    # Properties that already have a (non-cancelled) ETV scheduled in the
    # current calendar year — every WEG without one "needs" one. Only OWNER
    # (WEG) properties hold Eigentümerversammlungen; SEV (STRATA) and
    # Mietverwaltung (RENTAL) never do, so they never get the flag.
    year_start = datetime(datetime.now(UTC).year, 1, 1, tzinfo=UTC)
    next_year_start = datetime(year_start.year + 1, 1, 1, tzinfo=UTC)
    props_with_etv: set[uuid.UUID] = set()
    if property_ids:
        etv_rows = await session.scalars(
            select(EtvAssembly.property_id)
            .where(
                EtvAssembly.organization_id == org_id,
                EtvAssembly.deleted_at.is_(None),
                EtvAssembly.property_id.in_(property_ids),
                EtvAssembly.status != AssemblyStatus.ABGESAGT,
                EtvAssembly.scheduled_start >= year_start,
                EtvAssembly.scheduled_start < next_year_start,
            )
            .distinct()
        )
        props_with_etv = set(etv_rows.all())

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
            units_count=unit_counts.get(p.id, 0),
            needs_current_year_etv=p.type == PropertyType.OWNER and p.id not in props_with_etv,
        )
        for p in rows
    ]


@router.get("/property-selection", response_model=AdminPropertySelectionResponse)
async def get_property_selection(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPropertySelectionResponse:
    """The org-wide checked-property set for the units/fee box. Shared by
    every Verwalter of the org; empty when nothing's been selected yet."""
    row = await session.scalar(
        select(OrganizationPropertySelection).where(
            OrganizationPropertySelection.organization_id == current_user.organization_id
        )
    )
    ids = [uuid.UUID(p) for p in row.property_ids] if row else []
    return AdminPropertySelectionResponse(property_ids=ids)


@router.put("/property-selection", response_model=AdminPropertySelectionResponse)
async def put_property_selection(
    payload: AdminPropertySelectionUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPropertySelectionResponse:
    """Replace the org-wide checked-property set (last write wins). Stale
    or foreign ids are dropped so the shared selection stays clean."""
    org_id = current_user.organization_id
    valid_ids: set[uuid.UUID] = set()
    if payload.property_ids:
        rows = await session.scalars(
            select(Property.id).where(
                Property.organization_id == org_id,
                Property.deleted_at.is_(None),
                Property.id.in_(payload.property_ids),
            )
        )
        valid_ids = set(rows.all())

    # Keep the caller's order, drop invalid ids + duplicates.
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for pid in payload.property_ids:
        if pid in valid_ids and pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    stored = [str(pid) for pid in ordered]

    row = await session.scalar(
        select(OrganizationPropertySelection).where(
            OrganizationPropertySelection.organization_id == org_id
        )
    )
    if row is None:
        session.add(
            OrganizationPropertySelection(
                organization_id=org_id,
                property_ids=stored,
                updated_by_user_id=current_user.id,
            )
        )
    else:
        row.property_ids = stored
        row.updated_by_user_id = current_user.id
    await session.commit()
    return AdminPropertySelectionResponse(property_ids=ordered)


@router.post(
    "/signature-requests",
    response_model=SignatureRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_signature_request_endpoint(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
    recipient_email: Annotated[str, Query()],
    recipient_name: Annotated[str | None, Query()] = None,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SignatureRequestResponse:
    """Send a PDF out for e-signature via DocuSeal — the signer is emailed
    (through SES) and signs without a portal account. Gated: 503 until
    DocuSeal is configured. Optional property_id files the signed PDF
    under that Liegenschaft."""
    client = get_docuseal_client(settings)
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signatur-Dienst ist nicht konfiguriert.",
        )

    email = recipient_email.strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empfänger-E-Mail fehlt."
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leere Datei.")
    if len(raw) > settings.document_max_bytes:
        max_mb = settings.document_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei darf höchstens {max_mb} MB groß sein.",
        )

    if property_id is not None:
        await _load_property_for_org(session, current_user.organization_id, property_id)

    try:
        row = await signatures_svc.create_signature_request(
            session,
            organization_id=current_user.organization_id,
            created_by_user_id=current_user.id,
            property_id=property_id,
            pdf_bytes=raw,
            filename=file.filename or "Dokument.pdf",
            recipient_email=email,
            recipient_name=(recipient_name or "").strip() or None,
            client=client,
        )
    except DocuSealError as exc:
        # Persist the FAILED row, then surface a 502 to the SPA.
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DocuSeal-Fehler: {exc}",
        ) from exc

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="signature_request_created",
            target_type="signature_requests",
            target_id=str(row.id),
            payload_json={"recipient_email": email, "filename": row.source_filename},
        )
    )
    await session.commit()
    await session.refresh(row)
    return SignatureRequestResponse.model_validate(row)


@router.get("/signature-requests", response_model=list[SignatureRequestResponse])
async def list_signature_requests(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SignatureRequestResponse]:
    rows = (
        await session.scalars(
            select(SignatureRequest)
            .where(SignatureRequest.organization_id == current_user.organization_id)
            .order_by(SignatureRequest.created_at.desc())
        )
    ).all()
    return [SignatureRequestResponse.model_validate(r) for r in rows]


@router.get("/units", response_model=list[AdminUnitListItem])
async def list_units(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 200,
) -> list[AdminUnitListItem]:
    capped = max(1, min(limit, 1000))
    rows = (
        await session.execute(
            select(Unit, Property.name, Property.type)
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
            voting_share=float(u.voting_share) if u.voting_share is not None else None,
            area_m2=float(u.area_m2) if u.area_m2 is not None else None,
            heated_area_m2=float(u.heated_area_m2) if u.heated_area_m2 is not None else None,
            persons=float(u.persons) if u.persons is not None else None,
            property_id=u.property_id,
            property_name=pname,
            property_type=ptype,
        )
        for u, pname, ptype in rows
    ]


@router.put(
    "/units/{unit_id}/distribution-keys",
    response_model=AdminUnitListItem,
)
async def update_unit_distribution_keys(
    unit_id: uuid.UUID,
    body: AdminUnitDistributionKeysUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminUnitListItem:
    """Manually overwrite the distribution-key cells (MEA / Fläche /
    Heizfläche / Personen). Sent by the admin SPA's inline editor
    today; will be sent by the browser extension once that lands
    (see ADR-0009).

    Only fields present in the request body are applied — `None` and
    "field omitted" are different intents from a partial-update
    perspective, but Pydantic exposes both as None. We treat them the
    same (write-through nullable column); the inline UI sends every
    field on save so this matches reality.
    """
    row = (
        await session.execute(
            select(Unit, Property.name, Property.type)
            .join(Property, Property.id == Unit.property_id)
            .where(
                Unit.id == unit_id,
                Unit.organization_id == current_user.organization_id,
                Unit.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    unit, pname, ptype = row

    unit.voting_share = body.voting_share
    unit.area_m2 = body.area_m2
    unit.heated_area_m2 = body.heated_area_m2
    unit.persons = body.persons

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="unit.distribution_keys.updated",
            target_type="units",
            target_id=str(unit.id),
            payload_json={
                "voting_share": body.voting_share,
                "area_m2": body.area_m2,
                "heated_area_m2": body.heated_area_m2,
                "persons": body.persons,
            },
        )
    )
    await session.commit()

    return AdminUnitListItem(
        id=unit.id,
        unit_hr_id=unit.unit_hr_id,
        type=unit.type.value,
        floor=unit.floor,
        position=unit.position,
        voting_share=float(unit.voting_share) if unit.voting_share is not None else None,
        area_m2=float(unit.area_m2) if unit.area_m2 is not None else None,
        heated_area_m2=float(unit.heated_area_m2) if unit.heated_area_m2 is not None else None,
        persons=float(unit.persons) if unit.persons is not None else None,
        property_id=unit.property_id,
        property_name=pname,
        property_type=ptype,
    )


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


# ── Documents (Item 6: folders + uploads + downloads) ─────────────


async def _load_property_for_org(
    session: AsyncSession, organization_id: uuid.UUID, property_id: uuid.UUID
) -> Property:
    """Fetch the property + verify org scope, or 404. Used by every
    document/folder endpoint as the first scope gate."""
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


async def _load_folder_for_property(
    session: AsyncSession,
    folder_id: uuid.UUID,
    property_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> DocumentFolder:
    """Load a folder, asserting it belongs to the given property + org.
    Same shape as `_load_property_for_org` so callers compose cleanly."""
    folder = await session.scalar(
        select(DocumentFolder).where(
            DocumentFolder.id == folder_id,
            DocumentFolder.property_id == property_id,
            DocumentFolder.organization_id == organization_id,
            DocumentFolder.deleted_at.is_(None),
        )
    )
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return folder


@router.get(
    "/properties/{property_id}/folders",
    response_model=list[DocumentFolderResponse],
)
async def list_property_folders(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentFolderResponse]:
    """Flat list of all folders for one property. The SPA recomposes the
    tree client-side — easier to render incrementally on mutation and
    avoids a recursive payload."""
    await _load_property_for_org(session, current_user.organization_id, property_id)
    rows = (
        await session.scalars(
            select(DocumentFolder)
            .where(
                DocumentFolder.property_id == property_id,
                DocumentFolder.organization_id == current_user.organization_id,
                DocumentFolder.deleted_at.is_(None),
            )
            .order_by(DocumentFolder.name)
        )
    ).all()
    return [DocumentFolderResponse.model_validate(f) for f in rows]


@router.post(
    "/properties/{property_id}/folders",
    response_model=DocumentFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    property_id: uuid.UUID,
    req: DocumentFolderCreateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentFolderResponse:
    await _load_property_for_org(session, current_user.organization_id, property_id)
    if req.parent_folder_id is not None:
        # Validate the parent belongs to the same property — silently
        # accepting a cross-property parent would leak / scramble trees.
        await _load_folder_for_property(
            session,
            req.parent_folder_id,
            property_id,
            current_user.organization_id,
        )
    folder = DocumentFolder(
        organization_id=current_user.organization_id,
        property_id=property_id,
        parent_folder_id=req.parent_folder_id,
        name=req.name.strip(),
    )
    session.add(folder)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="document_folder_created",
            target_type="document_folders",
            target_id=str(folder.id),
            payload_json={
                "property_id": str(property_id),
                "parent_folder_id": str(req.parent_folder_id) if req.parent_folder_id else None,
                "name": folder.name,
            },
        )
    )
    await session.commit()
    await session.refresh(folder)
    return DocumentFolderResponse.model_validate(folder)


@router.patch("/folders/{folder_id}", response_model=DocumentFolderResponse)
async def update_folder(
    folder_id: uuid.UUID,
    req: DocumentFolderUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentFolderResponse:
    """Rename and/or re-parent a folder. `parent_folder_id` is honoured
    only when explicitly present in the request body — Pydantic v2's
    `model_fields_set` lets us tell "omitted" from "explicit null"."""
    folder = await session.scalar(
        select(DocumentFolder).where(
            DocumentFolder.id == folder_id,
            DocumentFolder.organization_id == current_user.organization_id,
            DocumentFolder.deleted_at.is_(None),
        )
    )
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    changed: dict[str, Any] = {}
    if req.name is not None:
        folder.name = req.name.strip()
        changed["name"] = folder.name
    if "parent_folder_id" in req.model_fields_set:
        new_parent = req.parent_folder_id
        if new_parent == folder.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ordner kann nicht sich selbst übergeordnet sein.",
            )
        if new_parent is not None:
            # Cycle check: walk the new-parent's ancestor chain and reject
            # if `folder.id` shows up. Worst-case O(depth) — trees stay
            # small in practice.
            cursor: uuid.UUID | None = new_parent
            visited: set[uuid.UUID] = set()
            while cursor is not None:
                if cursor == folder.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Verschiebung würde einen Zyklus erzeugen.",
                    )
                if cursor in visited:
                    break  # defensive — DB shouldn't already have a cycle
                visited.add(cursor)
                parent_row = await session.scalar(
                    select(DocumentFolder).where(
                        DocumentFolder.id == cursor,
                        DocumentFolder.organization_id == current_user.organization_id,
                        DocumentFolder.deleted_at.is_(None),
                    )
                )
                if parent_row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Übergeordneter Ordner nicht gefunden.",
                    )
                if parent_row.property_id != folder.property_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Ordner kann nur innerhalb derselben Liegenschaft verschoben werden."
                        ),
                    )
                cursor = parent_row.parent_folder_id
        folder.parent_folder_id = new_parent
        changed["parent_folder_id"] = str(new_parent) if new_parent else None

    if changed:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="document_folder_updated",
                target_type="document_folders",
                target_id=str(folder.id),
                payload_json=changed,
            )
        )
        await session.commit()
        await session.refresh(folder)
    return DocumentFolderResponse.model_validate(folder)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete a folder. Refuses to delete non-empty folders so
    Verwalter has to consciously move contents first — protects against
    a careless click wiping a year of protocols."""
    folder = await session.scalar(
        select(DocumentFolder).where(
            DocumentFolder.id == folder_id,
            DocumentFolder.organization_id == current_user.organization_id,
            DocumentFolder.deleted_at.is_(None),
        )
    )
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    child_folder_count = await session.scalar(
        select(func.count(DocumentFolder.id)).where(
            DocumentFolder.parent_folder_id == folder.id,
            DocumentFolder.deleted_at.is_(None),
        )
    )
    doc_count = await session.scalar(
        select(func.count(Document.id)).where(
            Document.folder_id == folder.id,
            Document.deleted_at.is_(None),
        )
    )
    if (child_folder_count or 0) > 0 or (doc_count or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ordner ist nicht leer.",
        )

    folder.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="document_folder_deleted",
            target_type="document_folders",
            target_id=str(folder.id),
            payload_json={"property_id": str(folder.property_id)},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/properties/{property_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_property_documents(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentResponse]:
    """All non-deleted docs for the property, regardless of folder.
    SPA filters by folder_id client-side from the same payload — keeps
    folder navigation snappy without per-folder round-trips."""
    await _load_property_for_org(session, current_user.organization_id, property_id)
    rows = (
        await session.scalars(
            select(Document)
            .where(
                Document.property_id == property_id,
                Document.organization_id == current_user.organization_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.issued_date.desc().nulls_last(), Document.name)
        )
    ).all()
    return [DocumentResponse.model_validate(d) for d in rows]


@router.post(
    "/properties/{property_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
    name: Annotated[str | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    kind: Annotated[str, Query()] = DocumentKind.SONSTIGES.value,
    visibility: Annotated[str, Query()] = DocumentVisibility.ALL.value,
) -> DocumentResponse:
    """Verwalter uploads a PDF / Office doc into the property tree.

    Query-string metadata keeps the multipart body simple (just the
    file). Defaults give a working upload with one click: kind goes
    SONSTIGES, visibility goes ALL so portal users see it immediately,
    no folder (root) unless one was picked in the UI.
    """
    prop = await _load_property_for_org(session, current_user.organization_id, property_id)
    if folder_id is not None:
        await _load_folder_for_property(
            session, folder_id, property_id, current_user.organization_id
        )

    raw = await file.read()
    if len(raw) > settings.document_max_bytes:
        max_mb = settings.document_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei darf höchstens {max_mb} MB groß sein.",
        )

    # Validate the enum strings the caller passed before we spend disk I/O.
    try:
        kind_enum = DocumentKind(kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannte Dokument-Art: {kind}",
        ) from exc
    try:
        visibility_enum = DocumentVisibility(visibility)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unbekannte Sichtbarkeit: {visibility}",
        ) from exc

    display_name = (name or file.filename or "Dokument").strip()
    doc = Document(
        organization_id=current_user.organization_id,
        property_id=prop.id,
        folder_id=folder_id,
        name=display_name,
        kind=kind_enum,
        visibility=visibility_enum,
        mime_type=file.content_type,
        size_bytes=len(raw),
        uploaded_at=datetime.now(UTC),
    )
    session.add(doc)
    await session.flush()  # need the id before we can pick a file path

    try:
        _, suffix = write_document(doc.id, file.filename or "upload.pdf", raw)
    except DocumentStorageError as exc:
        # No commit yet — the orphan Document row is just rolled back.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Datei: {exc}",
        ) from exc

    # `local-disk:<suffix>` marks rows whose bytes live in our document
    # directory. Pre-existing Impower-imported rows have a remote URL
    # here (or NULL) — the download endpoint switches on this prefix.
    doc.storage_url = f"local-disk:{suffix}"
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="document_uploaded",
            target_type="documents",
            target_id=str(doc.id),
            payload_json={
                "property_id": str(prop.id),
                "folder_id": str(folder_id) if folder_id else None,
                "size_bytes": len(raw),
                "mime_type": file.content_type,
            },
        )
    )
    await session.commit()
    await session.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.patch("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    req: DocumentUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentResponse:
    """Rename, re-file, or re-tag a document. Same `model_fields_set`
    trick on folder_id so callers can explicitly send `null` to move
    a doc back to the property root."""
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == current_user.organization_id,
            Document.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    changed: dict[str, Any] = {}
    if req.name is not None:
        doc.name = req.name.strip()
        changed["name"] = doc.name
    if "folder_id" in req.model_fields_set:
        if req.folder_id is not None:
            if doc.property_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Dokument hat keine Liegenschaft.",
                )
            await _load_folder_for_property(
                session,
                req.folder_id,
                doc.property_id,
                current_user.organization_id,
            )
        doc.folder_id = req.folder_id
        changed["folder_id"] = str(req.folder_id) if req.folder_id else None
    if req.visibility is not None:
        try:
            doc.visibility = DocumentVisibility(req.visibility)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unbekannte Sichtbarkeit: {req.visibility}",
            ) from exc
        changed["visibility"] = doc.visibility.value
    if req.kind is not None:
        try:
            doc.kind = DocumentKind(req.kind)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unbekannte Dokument-Art: {req.kind}",
            ) from exc
        changed["kind"] = doc.kind.value
    if req.issued_date is not None:
        doc.issued_date = req.issued_date
        changed["issued_date"] = req.issued_date.isoformat()

    if changed:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="document_updated",
                target_type="documents",
                target_id=str(doc.id),
                payload_json=changed,
            )
        )
        await session.commit()
        await session.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete a document. On-disk bytes go too — there's no
    "trash" recovery for v1 and keeping them around just costs storage."""
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == current_user.organization_id,
            Document.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Only wipe disk bytes for docs we actually own on disk.
    if doc.storage_url and doc.storage_url.startswith("local-disk:"):
        suffix = doc.storage_url[len("local-disk:") :]
        storage_delete_document(doc.id, suffix)

    doc.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="document_deleted",
            target_type="documents",
            target_id=str(doc.id),
            payload_json={"property_id": str(doc.property_id) if doc.property_id else None},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/file")
async def download_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Authenticated document download for the Verwalter.

    Not a StaticFiles mount because documents carry visibility scopes.
    Verwalter can see anything in their org. Source order mirrors the
    portal endpoint (me.py `download_my_document`):
      1. Local-disk cache (Verwalter-uploaded docs) when storage_url
         carries the `local-disk:` marker and the file is present.
      2. Impower's `/documents/{impower_id}/download` on demand — most
         Impower-synced docs (Abrechnungen, Rechnungen) live ONLY on
         Impower's side, so this is the common path, not the exception.
    """
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == current_user.organization_id,
            Document.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Filename / RFC 6266 helpers are shared with the portal endpoint.
    from app.api.v1.me import _ascii_fallback, _rfc5987, _safe_download_filename

    download_name = _safe_download_filename(doc.name, doc.mime_type, doc.storage_url)

    # 1. Local-disk cache — fastest, no Impower round-trip.
    if doc.storage_url and doc.storage_url.startswith("local-disk:"):
        suffix = doc.storage_url[len("local-disk:") :]
        path = document_path(doc.id, suffix)
        if path.exists():
            return FileResponse(
                path,
                media_type=doc.mime_type or "application/octet-stream",
                filename=download_name,
            )

    # 2. Impower on-demand fallback (the common path for synced docs).
    if doc.impower_id is not None and settings.impower_api_token:
        from app.integrations.impower.client import ImpowerClient, ImpowerError

        try:
            async with ImpowerClient(
                settings.impower_api_base, settings.impower_api_token
            ) as client:
                data = await client.download_document_content(int(doc.impower_id))
        except ImpowerError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Datei konnte nicht von Impower geladen werden.",
            ) from None
        if data is not None:
            return Response(
                content=data,
                media_type=doc.mime_type or "application/pdf",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{_ascii_fallback(download_name)}"; '
                        f"filename*=UTF-8''{_rfc5987(download_name)}"
                    ),
                },
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Datei ist nicht verfügbar.",
    )


@router.get("/property-images/{filename}")
async def download_property_image(
    filename: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Authenticated read of a property hero photo. Replaces the old public
    StaticFiles mount: any signed-in user in the org may fetch (portal owners
    see the photo in the property switcher, Verwalter in the admin), but it's
    no longer world-readable.

    `filename` is `{property_id}.png`; we parse the id and rebuild the path
    via the storage helper, so a crafted filename can't traverse the dir.
    Not VERWALTER-only on purpose — owners/tenants render the same photo.
    """
    stem = filename[:-4] if filename.endswith(".png") else filename
    try:
        property_id = uuid.UUID(stem)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = property_image_path(property_id)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(path, media_type="image/png")


# =================================================================
# Per-property contacts + bulk invite
# =================================================================


def _role_for_contract_type(t: ContractType) -> UserRole | None:
    """Map Impower contract types to portal user roles.

    OWNER + PROPERTY_OWNER → EIGENTUEMER. TENANT → MIETER. Anything
    new from Impower without an explicit mapping returns None and
    the bulk endpoint skips that contact (the Verwalter can still
    invite manually via /admin/invites/new picking the role).
    """
    if t in (ContractType.OWNER, ContractType.PROPERTY_OWNER):
        return UserRole.EIGENTUEMER
    if t == ContractType.TENANT:
        return UserRole.MIETER
    return None


async def _load_property_contacts(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> list[tuple[Contact, ContractType]]:
    """Distinct (Contact, contract_type) rows linked to a property
    via active contracts. Companies are included — the Einladungen
    tab shows them as non-invitable rows so the Verwalter can see
    the full link graph."""
    stmt = (
        select(Contact, Contract.type)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            Contract.property_id == property_id,
            Contract.organization_id == organization_id,
            Contract.deleted_at.is_(None),
            Contact.deleted_at.is_(None),
        )
        .order_by(Contact.last_name.asc().nulls_last(), Contact.company_name.asc().nulls_last())
    )
    rows = (await session.execute(stmt)).all()
    # Dedupe by contact_id (a contact can be on multiple contracts —
    # the SPA only cares about the contact once; pick the first
    # contract type seen).
    seen: dict[uuid.UUID, tuple[Contact, ContractType]] = {}
    for contact, ctype in rows:
        if contact.id not in seen:
            seen[contact.id] = (contact, ctype)
    return list(seen.values())


@router.get(
    "/properties/{property_id}/contacts",
    response_model=list[AdminPropertyContactResponse],
)
async def list_property_contacts(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AdminPropertyContactResponse]:
    """Contacts linked to a property via active contracts, enriched
    with account / pending-invite status for the Einladungen tab."""
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    pairs = await _load_property_contacts(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
    )
    if not pairs:
        return []

    impower_ids = [c.impower_id for c, _ in pairs if c.impower_id is not None]
    accounts: set[int] = set()
    if impower_ids:
        rows = (
            await session.execute(
                select(User.contact_id_impower).where(
                    User.organization_id == current_user.organization_id,
                    User.contact_id_impower.in_(impower_ids),
                    User.deleted_at.is_(None),
                )
            )
        ).all()
        accounts = {r[0] for r in rows if r[0] is not None}

    now = datetime.now(UTC)
    pending_by_impower: dict[int, InviteCode] = {}
    last_invited_by_impower: dict[int, datetime] = {}
    if impower_ids:
        invites = (
            (
                await session.execute(
                    select(InviteCode)
                    .where(
                        InviteCode.organization_id == current_user.organization_id,
                        InviteCode.contact_id_impower.in_(impower_ids),
                    )
                    .order_by(InviteCode.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for inv in invites:
            iid = inv.contact_id_impower
            if iid is None:
                continue
            # First write wins (we ordered desc) → captures the most
            # recent invite per contact, which is what the UI labels
            # as last_invited_at.
            last_invited_by_impower.setdefault(iid, inv.created_at)
            if inv.consumed_at is None and inv.expires_at > now and iid not in pending_by_impower:
                pending_by_impower[iid] = inv

    out: list[AdminPropertyContactResponse] = []
    for contact, ctype in pairs:
        suggested = _role_for_contract_type(ctype) or UserRole.EIGENTUEMER
        pending = (
            pending_by_impower.get(contact.impower_id) if contact.impower_id is not None else None
        )
        out.append(
            AdminPropertyContactResponse(
                contact_id=contact.id,
                impower_id=contact.impower_id,
                name=_contact_display_name(contact) or "(unbenannt)",
                email=contact.email,
                phone=contact.phone,
                contract_type=ctype.value,
                suggested_role=suggested,
                has_user_account=(
                    contact.impower_id is not None and contact.impower_id in accounts
                ),
                pending_invite=(
                    AdminPropertyContactInviteInfo(
                        code=pending.code,
                        expires_at=pending.expires_at,
                        created_at=pending.created_at,
                    )
                    if pending is not None
                    else None
                ),
                last_invited_at=(
                    last_invited_by_impower.get(contact.impower_id)
                    if contact.impower_id is not None
                    else None
                ),
            )
        )
    return out


@router.post(
    "/properties/{property_id}/invites/bulk",
    response_model=BulkInviteResponse,
)
async def bulk_invite_property_contacts(
    property_id: uuid.UUID,
    req: BulkInviteRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> BulkInviteResponse:
    """Create or refresh invites for N contacts at once.

    Per contact:
      - Skip if no email (no_email).
      - Skip if a user account exists for the contact's
        impower_id (account_exists).
      - Skip if the contact's contract type doesn't map to a role
        (no_role) — Verwalter must invite manually.
      - If a pending unconsumed invite exists, invalidate it
        (expires_at = now - 1s) and issue a fresh code (resent).
      - Otherwise issue a new code (sent).
      - Email is best-effort; a failed send still creates the
        invite row + records the failure in the outcome.

    All audited under one `bulk_invite_dispatched` action with the
    full per-contact outcome list.
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

    # Pre-load all candidate contacts WITH their contract type so we
    # can map role. Filter to the explicitly-requested IDs.
    pairs = await _load_property_contacts(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
    )
    by_id = {c.id: (c, ctype) for c, ctype in pairs}

    requested = [cid for cid in req.contact_ids if cid in by_id]
    if not requested:
        return BulkInviteResponse(outcomes=[])

    candidates = [by_id[cid] for cid in requested]
    impower_ids = [c.impower_id for c, _ in candidates if c.impower_id is not None]

    now = datetime.now(UTC)
    accounts: set[int] = set()
    pending_by_impower: dict[int, InviteCode] = {}
    if impower_ids:
        account_rows = (
            await session.execute(
                select(User.contact_id_impower).where(
                    User.organization_id == current_user.organization_id,
                    User.contact_id_impower.in_(impower_ids),
                    User.deleted_at.is_(None),
                )
            )
        ).all()
        accounts = {r[0] for r in account_rows if r[0] is not None}

        pending_rows = (
            (
                await session.execute(
                    select(InviteCode).where(
                        InviteCode.organization_id == current_user.organization_id,
                        InviteCode.contact_id_impower.in_(impower_ids),
                        InviteCode.consumed_at.is_(None),
                        InviteCode.expires_at > now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for inv in pending_rows:
            if inv.contact_id_impower is not None:
                pending_by_impower[inv.contact_id_impower] = inv

    outcomes: list[BulkInviteOutcome] = []
    for contact, ctype in candidates:
        # 1. Has account?
        if contact.impower_id is not None and contact.impower_id in accounts:
            outcomes.append(
                BulkInviteOutcome(
                    contact_id=contact.id,
                    status=BulkInviteOutcomeStatus.SKIPPED_ACCOUNT_EXISTS,
                    email=contact.email,
                )
            )
            continue

        # 2. No email?
        if not contact.email:
            outcomes.append(
                BulkInviteOutcome(
                    contact_id=contact.id,
                    status=BulkInviteOutcomeStatus.SKIPPED_NO_EMAIL,
                )
            )
            continue

        # 3. Role mappable?
        role = _role_for_contract_type(ctype)
        if role is None:
            outcomes.append(
                BulkInviteOutcome(
                    contact_id=contact.id,
                    status=BulkInviteOutcomeStatus.SKIPPED_NO_ROLE,
                    email=contact.email,
                    reason=f"contract_type {ctype.value} has no role mapping",
                )
            )
            continue

        # 4. Invalidate any pending invite for this impower_id.
        is_resend = False
        if contact.impower_id is not None and contact.impower_id in pending_by_impower:
            stale = pending_by_impower[contact.impower_id]
            stale.expires_at = now - timedelta(seconds=1)
            is_resend = True

        # 5. Create + send.
        code = generate_invite_code()
        expires_at = now + timedelta(days=req.ttl_days)
        invite = InviteCode(
            organization_id=current_user.organization_id,
            code=code,
            email=contact.email.lower(),
            contact_id_impower=contact.impower_id,
            role=role,
            scope_json={"property_id": str(property_id)},
            expires_at=expires_at,
            created_by=current_user.id,
        )
        session.add(invite)
        try:
            await session.flush()
        except Exception as exc:  # pragma: no cover — defensive
            outcomes.append(
                BulkInviteOutcome(
                    contact_id=contact.id,
                    status=BulkInviteOutcomeStatus.FAILED,
                    email=contact.email,
                    reason=str(exc)[:200],
                )
            )
            continue

        email_error: str | None = None
        try:
            subject, html_body, text_body = render_invite_email(contact.email, code, role.value)
            # Send is best-effort — the invite row exists regardless,
            # and the per-contact outcome carries any error so the
            # SPA can surface "Erneut senden" for the failed ones.
            await email_client.send(
                to=contact.email,
                subject=subject,
                html=html_body,
                text=text_body,
            )
        except EmailError as exc:
            email_error = str(exc)

        outcomes.append(
            BulkInviteOutcome(
                contact_id=contact.id,
                status=(
                    BulkInviteOutcomeStatus.RESENT if is_resend else BulkInviteOutcomeStatus.SENT
                ),
                code=code,
                email=contact.email,
                reason=email_error[:200] if email_error else None,
            )
        )

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="bulk_invite_dispatched",
            target_type="properties",
            target_id=str(property_id),
            payload_json={
                "requested_count": len(req.contact_ids),
                "outcomes": [
                    {"contact_id": str(o.contact_id), "status": o.status.value} for o in outcomes
                ],
            },
        )
    )
    await session.commit()
    return BulkInviteResponse(outcomes=outcomes)
