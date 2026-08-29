import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.storage.avatars import AvatarError, delete_avatar, write_avatar
from app.integrations.storage.documents import document_path
from app.models import (
    AuditLog,
    Contact,
    Contract,
    ContractContact,
    DeviceEnvironment,
    DevicePlatform,
    Document,
    DocumentFolder,
    DocumentKind,
    Property,
    Unit,
    User,
    UserDevice,
    UserRole,
)
from app.models import (
    Session as DbSession,
)
from app.models._mixins import uuid7_pk
from app.models.property import PropertyState
from app.schemas.account import HausgeldAccountResponse
from app.schemas.auth import UserResponse
from app.schemas.contact import ContactDetailResponse, ContractContextResponse
from app.schemas.device import RegisterDeviceRequest
from app.schemas.document import DocumentFolderResponse, DocumentResponse
from app.schemas.invoice import InvoiceDetailResponse, InvoiceLineItemResponse
from app.schemas.notification import (
    NotificationSetting,
    NotificationSettingsResponse,
    UpdateNotificationSettingsRequest,
)
from app.schemas.property import PropertyDetailResponse, PropertyResponse
from app.schemas.rent_settlement import RentSettlementResponse
from app.schemas.unit import UnitResponse
from app.schemas.vendor import VendorSummary
from app.services import notification_prefs
from app.services import units as units_svc
from app.services import vendors as vendors_svc
from app.services.access import active_contract_filter, active_property_filter
from app.services.activity import ActivityItem, build_activity_feed
from app.services.document_release import RELEASE_GATED_KINDS
from app.services.reversed_invoices import get_reversed_invoice_cache

router = APIRouter(prefix="/me", tags=["me"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role.value,
        organization_id=user.organization_id,
        contact_id_impower=user.contact_id_impower,
        avatar_url=user.avatar_url,
    )


@router.get("", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _to_user_response(current_user)


@router.post("/devices", status_code=status.HTTP_204_NO_CONTENT)
async def register_device(
    body: RegisterDeviceRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Register (or refresh) this device's APNs token for push.

    Upsert on the token: a re-register from the same device just
    bumps `last_seen_at` + re-points the row at the current user (so
    a shared iPad that switches accounts moves the token to whoever
    is signed in) + un-deletes it if it had been pruned. The unique
    constraint on `apns_token` makes the conflict target stable.
    """
    now = datetime.now(UTC)
    env = (
        DeviceEnvironment.SANDBOX if body.environment == "SANDBOX" else DeviceEnvironment.PRODUCTION
    )
    stmt = (
        pg_insert(UserDevice)
        .values(
            id=uuid7_pk(),
            user_id=current_user.id,
            apns_token=body.apns_token,
            platform=DevicePlatform.IOS,
            environment=env,
            created_at=now,
            last_seen_at=now,
            deleted_at=None,
        )
        .on_conflict_do_update(
            index_elements=["apns_token"],
            set_={
                "user_id": current_user.id,
                "environment": env,
                "last_seen_at": now,
                "deleted_at": None,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/devices/{apns_token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    apns_token: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Drop this device's token — called on sign-out so a signed-out
    phone stops receiving the previous user's notifications. Scoped
    to the caller's own tokens so one user can't unregister another's
    device. Idempotent: unknown / already-gone tokens 204 anyway."""
    await session.execute(
        update(UserDevice)
        .where(
            UserDevice.apns_token == apns_token,
            UserDevice.user_id == current_user.id,
            UserDevice.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notification-settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSettingsResponse:
    """The caller's full Push/E-Mail matrix. Categories without a saved
    row come back as all-on (opt-out default), so the client always
    renders the complete set. Shared by the portal + iOS settings."""
    effective = await notification_prefs.get_effective_settings(session, user_id=current_user.id)
    return NotificationSettingsResponse(
        items=[
            NotificationSetting(category=category, push=push, email=email)
            for category, (push, email) in effective.items()
        ]
    )


@router.put("/notification-settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    body: UpdateNotificationSettingsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationSettingsResponse:
    """Upsert the caller's matrix. The client sends the full set; we
    persist one row per category. Returns the re-read effective matrix
    so the client can confirm what stuck."""
    await notification_prefs.set_settings(
        session,
        user_id=current_user.id,
        settings={item.category: (item.push, item.email) for item in body.items},
    )
    await session.commit()
    effective = await notification_prefs.get_effective_settings(session, user_id=current_user.id)
    return NotificationSettingsResponse(
        items=[
            NotificationSetting(category=category, push=push, email=email)
            for category, (push, email) in effective.items()
        ]
    )


@router.put("/avatar", response_model=UserResponse)
async def upload_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> UserResponse:
    """Upload (or replace) the caller's avatar image.

    Accepts JPEG/PNG/WebP/GIF/BMP up to `settings.avatar_max_bytes`; Pillow
    normalises every upload to a 256x256 PNG. The stored URL carries a
    cache-bust `?v={mtime}` query so SPA refreshes pick up changes.
    """
    raw = await file.read()
    if len(raw) > settings.avatar_max_bytes:
        max_mb = settings.avatar_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar darf höchstens {max_mb} MB groß sein.",
        )
    try:
        url = write_avatar(current_user.id, raw)
    except AvatarError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Bilddatei: {exc}",
        ) from exc

    current_user.avatar_url = url
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="avatar_updated",
            target_type="users",
            target_id=str(current_user.id),
            payload_json={"size_bytes": len(raw)},
        )
    )
    await session.commit()
    await session.refresh(current_user)
    return _to_user_response(current_user)


@router.delete("/avatar", response_model=UserResponse)
async def remove_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Remove the caller's avatar — Layout falls back to initials."""
    delete_avatar(current_user.id)
    current_user.avatar_url = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="avatar_deleted",
            target_type="users",
            target_id=str(current_user.id),
            payload_json={},
        )
    )
    await session.commit()
    await session.refresh(current_user)
    return _to_user_response(current_user)


def _visible_properties_stmt(user: User):  # type: ignore[no-untyped-def]
    """Build a SELECT statement for properties visible to the given user.

    VERWALTER sees all org properties; other roles are scoped via
    contact_id_impower → contract_contacts → contracts → properties.

    For non-VERWALTER roles we also require `state == READY` — portal
    + iOS users should never see DRAFT or DISABLED properties (the
    Verwalter is still onboarding / cleaning them up). The admin SPA
    deliberately keeps the unfiltered statement via `_admin_*` paths
    in `app/api/v1/admin.py` so Verwalter can finish the onboarding
    work before flipping the state to READY.
    """
    base = select(Property).where(
        Property.organization_id == user.organization_id,
        Property.deleted_at.is_(None),
    )
    if user.role == UserRole.VERWALTER:
        # Field surfaces only (app, CarPlay, Siri): an object still in DRAFT
        # is not one the Verwalter drives to. Onboarding happens in the
        # admin SPA, which queries `/admin/*` without this filter.
        return base.where(active_property_filter())
    return (
        base.where(Property.state == PropertyState.READY)
        .join(Contract, Contract.property_id == Property.id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(Contact.impower_id == user.contact_id_impower)
        # Only contracts still in force — a sold/ended contract no
        # longer grants access to the Liegenschaft.
        .where(active_contract_filter())
        .distinct()
    )


def _document_visibility_filter(user: User):  # type: ignore[no-untyped-def]
    """Row-scope filter for non-Verwalter callers on the documents tab.

    Impower scopes a document to a specific unit / contract / contact via
    its `unitId` / `contractId` / `contactId` fields (mirrored onto our
    `documents.unit_id|contract_id|contact_id` columns). A doc that's
    pinned to Unit 1 must NOT show up in the documents tab for the Mieter
    of Unit 4. The rule:

    * Property-wide docs (all three FKs NULL) — always visible. Impower
      leaves the owner FKs empty only for genuinely WEG-level documents
      (e.g. the Gesamtabrechnung / Gesamtwirtschaftsplan that every owner is
      entitled to); the individual per-owner Abrechnungen carry an owner FK
      and fall under the scoped branches below. We trust that attribution —
      see ADR-0014 and the prod attribution probe (#153).
    * Unit-scoped docs — visible only if the caller is on a contract for
      that unit.
    * Contract-scoped docs — visible only if the caller is on that
      contract (via contract_contacts → contact → impower_id).
    * Contact-scoped docs — visible only if the caller's own contact
      (matched by contact_id_impower) is the target.

    `building_id` is intentionally NOT part of the gate: an
    Impower-imported doc that targets a whole building stays visible to
    every member of the property, matching the "all three NULL" branch
    semantically.

    Verwalter sees everything — call this only after the role check.

    This filter is the single source of truth for document ACL: the RAG
    assistant reuses it verbatim (app/rag/retrieval.py), so the same rule
    applies to the assistant too.
    """
    caller_contracts = (
        select(Contract.id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(Contact.impower_id == user.contact_id_impower)
        .where(active_contract_filter())
        .scalar_subquery()
    )
    caller_units = (
        select(Contract.unit_id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(
            Contact.impower_id == user.contact_id_impower,
            Contract.unit_id.is_not(None),
        )
        .where(active_contract_filter())
        .scalar_subquery()
    )
    caller_contact = (
        select(Contact.id).where(Contact.impower_id == user.contact_id_impower).scalar_subquery()
    )
    scope_ok = or_(
        and_(
            Document.unit_id.is_(None),
            Document.contract_id.is_(None),
            Document.contact_id.is_(None),
        ),
        Document.unit_id.in_(caller_units),
        Document.contract_id.in_(caller_contracts),
        Document.contact_id.in_(caller_contact),
    )
    # Visibility gate — enforced since the SEPA-Mandat leak: the Verwalter's
    # dropdown (PRIVATE/BEIRAT_ONLY/OWNERS/TENANTS/ALL) now actually gates the
    # portal. PRIVATE keeps ONE exception: a document personally pinned to the
    # caller (their Einzelabrechnung, their own SEPA mandate) stays theirs.
    from app.models import DocumentVisibility

    allowed = [DocumentVisibility.ALL]
    if user.role in (UserRole.EIGENTUEMER, UserRole.BEIRAT):
        allowed.append(DocumentVisibility.OWNERS)
    if user.role == UserRole.MIETER:
        allowed.append(DocumentVisibility.TENANTS)
    if user.role == UserRole.BEIRAT:
        allowed.append(DocumentVisibility.BEIRAT_ONLY)
    visibility_ok = or_(
        Document.visibility.in_(allowed),
        and_(
            Document.visibility == DocumentVisibility.PRIVATE,
            or_(
                Document.unit_id.in_(caller_units),
                Document.contract_id.in_(caller_contracts),
                Document.contact_id.in_(caller_contact),
            ),
        ),
    )
    # Freigabe-Schranke: Jahresabrechnung und Wirtschaftsplan erscheinen erst,
    # wenn der Verwalter sie freigegeben hat. Impower exportiert diese PDFs
    # auch als ENTWURF und markiert das nirgends (B42, 2026-08-29: Entwuerfe
    # wurden gespiegelt und benachrichtigt). Alle anderen Arten sind sofort
    # sichtbar wie bisher. Greift fuer Portal, Download UND den RAG-Scope der
    # Eigentuemer (retrieval.py nutzt genau diesen Filter).
    release_ok = or_(
        Document.kind.notin_(RELEASE_GATED_KINDS),
        Document.released_at.is_not(None),
    )
    return and_(scope_ok, visibility_ok, release_ok)


def _invoice_visibility_filter(user: User):  # type: ignore[no-untyped-def]
    """Visibility for the Dienstleister (vendor) invoice path.

    A vendor invoice is ``kind=RECHNUNG`` pinned to the VENDOR's
    ``contact_id`` (the vendors service buckets by it) with no unit/
    contract FK — i.e. a WEG-wide expense every owner of the property is
    entitled to see (it's part of the Abrechnung). The generic
    ``_document_visibility_filter`` only matches a doc's ``contact_id``
    against the CALLER's own contact, so it wrongly hid vendor invoices
    from owners: the list (property-wide, no filter) showed them, but the
    detail + PDF download 404'd ("Invoice not found" / "Download failed").

    So for invoices we additionally admit any ``RECHNUNG`` with no unit/
    contract pin. A RECHNUNG that IS pinned to a unit/contract
    (Sondereigentum repair billed to one owner) stays scoped via the base
    filter. The caller's property access is still enforced separately, so
    this never crosses a property boundary."""
    from app.models import DocumentVisibility

    return or_(
        _document_visibility_filter(user),
        and_(
            Document.kind == DocumentKind.RECHNUNG,
            Document.unit_id.is_(None),
            Document.contract_id.is_(None),
            Document.visibility == DocumentVisibility.ALL,
        ),
    )


@router.get("/properties", response_model=list[PropertyResponse])
async def get_my_properties(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PropertyResponse]:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        return []
    stmt = _visible_properties_stmt(current_user).order_by(Property.name)
    rows = (await session.scalars(stmt)).all()
    return [PropertyResponse.model_validate(p) for p in rows]


@router.get("/activity", response_model=list[ActivityItem])
async def get_my_activity(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[ActivityItem]:
    """Unified "Was gibt's Neues" feed for the iOS home-screen widget.

    One call returns a ready-sorted, ACL-scoped list of recent +
    actionable events (Beschlüsse, ETV, Dokumente, Rechnungen,
    Mitteilungen, Kalender, Zählerstand-Erinnerungen) across every
    Liegenschaft the caller can see. Visibility is resolved here with the
    exact same primitives as the other /me endpoints and handed to the
    aggregation service, so the feed never crosses a property/owner
    boundary."""
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        return []

    property_rows = list((await session.scalars(_visible_properties_stmt(current_user))).all())
    if not property_rows:
        return []

    # Storno bookings must not be announced in the widget either — the
    # deep link would land on a detail that (correctly) 404s. Impower
    # invoice ids are globally unique, so unioning across the caller's
    # properties can't leak one property's storno into another's feed.
    reversed_ids: set[int] | None = None
    if current_user.role != UserRole.VERWALTER:
        cache = get_reversed_invoice_cache()
        collected: set[int] = set()
        for prop_row in property_rows:
            if prop_row.impower_id is not None:
                collected |= await cache.get(prop_row.impower_id, settings)
        reversed_ids = collected

    return await build_activity_feed(
        session,
        user=current_user,
        property_rows=property_rows,
        doc_filter=_document_visibility_filter(current_user),
        invoice_filter=_invoice_visibility_filter(current_user),
        today=date.today(),
        now=datetime.now(UTC),
        limit=limit,
        reversed_invoice_ids=reversed_ids,
    )


@router.get("/properties/{property_id}", response_model=PropertyDetailResponse)
async def get_my_property(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PropertyDetailResponse:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    unit_rows = (
        await session.scalars(
            select(Unit)
            .where(Unit.property_id == prop.id, Unit.deleted_at.is_(None))
            .order_by(Unit.unit_rank.nulls_last(), Unit.unit_hr_id)
        )
    ).all()

    # Master-table enrichment: join contracts + contacts so each
    # unit carries its currently-active contracts (owner, tenant)
    # with role-tagged contact labels. The clients display the
    # rendered names without reimplementing person/company logic.
    contracts_by_unit = await units_svc.load_current_contracts_for_property(
        session, property_id=prop.id
    )
    unit_responses: list[UnitResponse] = []
    for u in unit_rows:
        ur = UnitResponse.model_validate(u)
        ur.current_contracts = contracts_by_unit.get(u.id, [])
        unit_responses.append(ur)

    return PropertyDetailResponse(
        **PropertyResponse.model_validate(prop).model_dump(),
        units=unit_responses,
    )


@router.get(
    "/contracts/{contract_id}/contacts/{contact_id}",
    response_model=ContactDetailResponse,
)
async def get_my_contract_contact(
    contract_id: uuid.UUID,
    contact_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContactDetailResponse:
    """Detail card for a contact reached via a specific contract.

    Authorization model: the contract's property must be in the
    caller's visible set, AND the contact must actually be on the
    contract (via contract_contacts). This means a Mieter on Unit 4
    can see the Eigentümer who's also on a contract for that unit's
    property — same data the chips already expose, just expanded.
    The Verwalter sees everything within their org. For everyone
    else, both joins act as scope checks.

    We collapse missing → 404 (not 403) so we don't disclose whether
    contract_id or contact_id exist when the caller has no access.
    """
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    # Pull the contract + property in a single query so we can apply
    # the property visibility join up-front. We don't reuse
    # `_visible_properties_stmt` directly because we'd then need to
    # round-trip property_id → contract; this single join is tighter.
    contract_q = (
        select(Contract)
        .join(Property, Property.id == Contract.property_id)
        .where(
            Contract.id == contract_id,
            Contract.organization_id == current_user.organization_id,
            Contract.deleted_at.is_(None),
            Property.deleted_at.is_(None),
        )
    )
    if current_user.role != UserRole.VERWALTER:
        # Same READY-only gate as the property list: a contract whose
        # property is still DRAFT shouldn't expose its participants.
        contract_q = contract_q.where(Property.state == PropertyState.READY)
    contract = await session.scalar(contract_q)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    # Non-Verwalter callers must themselves still belong to this
    # contract's property via an ACTIVE contract. This closes the
    # former-owner case (their own contract carries a past end_date) and
    # makes the property-membership check explicit rather than relying
    # on the UI to only surface chips the caller could already see.
    if current_user.role != UserRole.VERWALTER:
        caller_on_property = await session.scalar(
            select(Contract.id)
            .join(ContractContact, ContractContact.contract_id == Contract.id)
            .join(Contact, Contact.id == ContractContact.contact_id)
            .where(
                Contract.property_id == contract.property_id,
                Contact.impower_id == current_user.contact_id_impower,
                active_contract_filter(),
            )
            .limit(1)
        )
        if caller_on_property is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    # Now the contact-on-contract link. Non-Verwalter callers must
    # themselves be on the contract chain — i.e. they share a contact
    # row (their contact_id_impower) with someone on the contract's
    # property. The visible-property join already guarantees this
    # transitively, so we only need to verify the requested contact
    # is actually a participant of this specific contract.
    link_q = (
        select(Contact, ContractContact.role)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .where(
            ContractContact.contract_id == contract.id,
            Contact.id == contact_id,
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
        )
    )
    link_row = (await session.execute(link_q)).one_or_none()
    if link_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    contact, role = link_row

    contract_ctx = ContractContextResponse.model_validate(contract).model_copy(
        update={"role": role}
    )

    # Privacy gate: the FULL card (Geburtsdatum, Anschrift, SEPA-Mandat,
    # E-Mail, Telefon, USt-ID, …) is "see your own data" — it belongs to the
    # contact themselves and the Verwalter. A co-owner/co-tenant reached via
    # the same contract only gets the identity line: who is this person.
    is_self = (
        current_user.contact_id_impower is not None
        and contact.impower_id == current_user.contact_id_impower
    )
    identity_fields = ("id", "kind", "salutation", "title", "first_name", "last_name")
    sensitive_fields = (
        "date_of_birth",
        "company_name",
        "vat_id",
        "trade_register_number",
        "recipient_name",
        "mandate_number",
        "email",
        "phone",
        "additional_contacts",
        "city",
        "street",
        "number",
        "postal_code",
        "country",
    )
    if current_user.role == UserRole.VERWALTER or is_self:
        exposed = dict.fromkeys(identity_fields + sensitive_fields)
        for k in exposed:
            exposed[k] = getattr(contact, k)
    else:
        exposed = {k: getattr(contact, k) for k in identity_fields}
        exposed.update(dict.fromkeys(sensitive_fields))
        # Companies keep their name — it's their identity, not private data.
        exposed["company_name"] = contact.company_name
    return ContactDetailResponse(
        **exposed,
        preferred_channel=contact.preferred_channel,
        contract=contract_ctx,
    )


@router.get("/properties/{property_id}/documents", response_model=list[DocumentResponse])
async def get_my_property_documents(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentResponse]:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    # Reuse the same scope check as /me/properties/{id}: if the property isn't visible,
    # return 404 (not 403) so we don't leak existence.
    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    doc_stmt = (
        select(Document)
        .where(Document.property_id == prop.id, Document.deleted_at.is_(None))
        .order_by(Document.issued_date.desc().nulls_last(), Document.name)
    )
    if current_user.role != UserRole.VERWALTER:
        doc_stmt = doc_stmt.where(_document_visibility_filter(current_user))
    doc_rows = (await session.scalars(doc_stmt)).all()

    # The Impower sync carries identical copies of many documents — one row
    # WITH issued_date and one without — which made the portal show a large
    # bogus "undated" section. Collapse copies (same name + size + kind +
    # scope), preferring the dated row, and surface the fold as
    # duplicate_count so the UI can hint "N identische Kopien".
    best: dict[tuple[object, ...], DocumentResponse] = {}
    order: list[tuple[object, ...]] = []
    for d in doc_rows:
        key = (d.name, d.size_bytes, d.kind, d.unit_id, d.contract_id, d.contact_id)
        resp = DocumentResponse.model_validate(d)
        cur = best.get(key)
        if cur is None:
            best[key] = resp
            order.append(key)
            continue
        cur.duplicate_count += 1
        # Prefer the dated copy; among dated ones keep the first (the query
        # already sorts issued_date DESC NULLS LAST).
        if cur.issued_date is None and resp.issued_date is not None:
            resp.duplicate_count = cur.duplicate_count
            best[key] = resp
    deduped = [best[k] for k in order]
    # Re-sort: winners that gained a date must leave the undated tail.
    deduped.sort(
        key=lambda r: ((r.issued_date is None), -(r.issued_date or date.min).toordinal(), r.name)
    )
    return deduped


@router.get(
    "/properties/{property_id}/vendors",
    response_model=list[VendorSummary],
)
async def get_my_property_vendors(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[VendorSummary]:
    """Vendor / Dienstleister aggregate for a property.

    Buckets the property's invoice documents by `contact_id` and
    returns one card per firm + invoice history. Owners use this to
    answer "who fixed the boiler last time" — the actionable bits
    (name + phone + email) plus a recent-invoices list that links
    back into the existing document downloader.

    Auth: same 404-on-no-access shape as the other property-scoped
    endpoints. We deliberately do NOT apply the per-document
    visibility filter here — vendors are property-wide context, not
    per-unit personal data. (Invoices themselves remain gated; this
    endpoint only exposes the aggregate / contactability metadata.)

    Storno bookings (Impower state REVERSED) are hidden from owners:
    a cancelled invoice is a bookkeeping correction and reads to an
    owner as a bill their WEG never received. The Verwalter keeps the
    full picture — they are the ones who need to see the correction.
    """
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    reversed_ids: set[int] | None = None
    if current_user.role != UserRole.VERWALTER and prop.impower_id is not None:
        reversed_ids = await get_reversed_invoice_cache().get(prop.impower_id, settings)

    return await vendors_svc.load_vendors_for_property(
        session, property_id=prop.id, reversed_invoice_ids=reversed_ids
    )


@router.get(
    "/properties/{property_id}/invoices/{document_id}",
    response_model=InvoiceDetailResponse,
)
async def get_my_invoice_detail(
    property_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvoiceDetailResponse:
    """Per-invoice detail dialog source.

    The Dienstleister tab shows the document row (filename, date,
    amount). Clicking the row opens a dialog that needs the actual
    bookkeeping breakdown — what account each line was posted to,
    booking text ("Primärenergie 01.01-31.12"), VAT split. That
    lives on Impower's `/v2/invoices/{id}` resource.

    We don't mirror invoices locally — high churn, read-once per
    user click. So we look up the document on our side (to verify
    property access + get the `sourceId` we need on Impower's side),
    then fetch from Impower on demand. The endpoint returns a
    narrow, owner-friendly shape rather than the raw 30-field
    InvoiceDto.

    Auth: caller must have access to the property AND the document
    must belong to that property and have a real `impower_id` /
    sourceType=INVOICE. 404 otherwise — same existence-leak hygiene
    as elsewhere.
    """
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    doc_stmt = select(Document).where(
        Document.id == document_id,
        Document.property_id == prop.id,
        Document.organization_id == current_user.organization_id,
        Document.deleted_at.is_(None),
    )
    if current_user.role != UserRole.VERWALTER:
        # Invoice-aware row scope: a WEG vendor invoice (RECHNUNG, no
        # unit/contract pin) is visible to every owner — matching the
        # property-wide vendor LIST — while a unit/contract-pinned invoice
        # stays scoped to the parties on it.
        doc_stmt = doc_stmt.where(_invoice_visibility_filter(current_user))
    doc = await session.scalar(doc_stmt)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    # The `sourceId` we mirrored from Impower's DocumentDto IS the
    # invoice id on the /v2/invoices side. Pull it out of raw_jsonb
    # since we never broke it into a typed column.
    raw = doc.raw_jsonb or {}
    invoice_id = raw.get("sourceId")
    if not isinstance(invoice_id, int):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buchungsdetails sind für dieses Dokument nicht verfügbar.",
        )

    if not settings.impower_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impower-Verbindung nicht konfiguriert.",
        )

    # In-process TTL cache absorbs the "click → close → click again"
    # burst pattern owners exhibit when looking at the same invoice
    # multiple times. The cache is keyed by Impower's invoice id —
    # the data doesn't vary per user, and authorization already
    # happened above before we got here.
    from app.services.invoice_cache import get_invoice_cache

    cache = get_invoice_cache()
    data = cache.get(invoice_id)
    if data is None:
        from app.integrations.impower.client import ImpowerClient, ImpowerError

        try:
            async with ImpowerClient(
                settings.impower_api_base, settings.impower_api_token
            ) as client:
                data = await client.get_invoice(invoice_id)
        except ImpowerError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Rechnungsdetails konnten nicht von Impower geladen werden.",
            ) from None
        await cache.set(invoice_id, data)

    # Defence in depth behind the list filter: a storno is hidden from the
    # vendor list, so an owner should not reach its detail either — via a
    # stale client, a bookmarked id, or a cancellation that happened after
    # the list was rendered. Verwalter still open it.
    if current_user.role != UserRole.VERWALTER and data.get("state") == "REVERSED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    return _impower_invoice_to_response(data)


@router.get(
    "/properties/{property_id}/account",
    response_model=HausgeldAccountResponse,
)
async def get_my_account(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HausgeldAccountResponse:
    """The caller's own Hausgeldkonto for a property — balance (signed
    sum of bookings) + booking history, pulled live from Impower's
    accounts + posting-items.

    Owner-facing: resolved via the caller's `contact_id_impower`, so a
    user only ever sees their own account. Verwalter (no contact id)
    have no personal Hausgeld account → 404. Property must be visible
    via an active contract (same gate as everywhere else)."""
    if current_user.contact_id_impower is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Kein Hausgeldkonto vorhanden."
        )

    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None or prop.impower_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Kein Hausgeldkonto vorhanden."
        )

    # The owner's Hausgeld account is keyed by their CONTRACT in Impower
    # (CONTACT-sourced accounts hold vendors/Kreditoren, not owners). Resolve
    # the caller's active contract impower-ids on this property.
    contract_impower_ids = [
        cid
        for cid in (
            await session.scalars(
                select(Contract.impower_id)
                .join(ContractContact, ContractContact.contract_id == Contract.id)
                .join(Contact, Contact.id == ContractContact.contact_id)
                .where(
                    Contact.impower_id == current_user.contact_id_impower,
                    Contract.property_id == prop.id,
                    Contract.impower_id.is_not(None),
                    active_contract_filter(),
                )
            )
        ).all()
        if cid is not None
    ]
    if not contract_impower_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Kein Hausgeldkonto vorhanden."
        )

    if not settings.impower_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impower-Verbindung nicht konfiguriert.",
        )

    from app.integrations.impower.client import ImpowerClient, ImpowerError
    from app.services import account as account_svc

    try:
        async with ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client:
            return await account_svc.load_my_account(
                client,
                property_impower_id=prop.impower_id,
                contract_impower_ids=contract_impower_ids,
            )
    except ImpowerError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Hausgeldkonto konnte nicht von Impower geladen werden.",
        ) from None


@router.get(
    "/properties/{property_id}/rent-settlements",
    response_model=list[RentSettlementResponse],
)
async def get_my_rent_settlements(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[RentSettlementResponse]:
    """MV-property owner Mietabrechnung — rental-income / payout
    statements per period for the caller's OWN owner contract(s) on the
    property. Empty for WEG properties or tenants (no owner
    settlements). 404 only when the property isn't visible to the
    caller; scoped to the caller's contract ids so no one sees another
    party's settlement."""
    if current_user.contact_id_impower is None:
        return []

    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Liegenschaft nicht gefunden."
        )
    if prop.impower_id is None:
        return []

    rows = await session.scalars(
        select(Contract.impower_id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(
            Contact.impower_id == current_user.contact_id_impower,
            Contract.property_id == prop.id,
            Contract.impower_id.is_not(None),
            Contract.deleted_at.is_(None),
            active_contract_filter(),
        )
    )
    contract_ids = [c for c in rows.all() if c is not None]
    if not contract_ids:
        return []

    if not settings.impower_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Impower-Verbindung nicht konfiguriert.",
        )

    from app.integrations.impower.client import ImpowerClient, ImpowerError
    from app.services import rent_settlement as rs_svc

    try:
        async with ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client:
            return await rs_svc.load_my_rent_settlements(client, contract_impower_ids=contract_ids)
    except ImpowerError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mietabrechnung konnte nicht von Impower geladen werden.",
        ) from None


def _impower_invoice_to_response(data: dict[str, object]) -> InvoiceDetailResponse:
    """Project Impower's raw InvoiceDto down to the fields the
    Dienstleister dialog renders. Defensive against missing keys —
    we treat absent/None as "not surfaced" rather than failing the
    whole response.
    """
    from datetime import date as date_cls
    from decimal import Decimal

    def _dec(v: object) -> Decimal | None:
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except (ValueError, ArithmeticError):
            return None

    def _date(v: object) -> date_cls | None:
        if not isinstance(v, str) or len(v) < 10:
            return None
        try:
            return date_cls.fromisoformat(v[:10])
        except ValueError:
            return None

    def _str(v: object) -> str | None:
        return v if isinstance(v, str) and v else None

    items_raw = data.get("items") or []
    items: list[InvoiceLineItemResponse] = []
    if isinstance(items_raw, list):
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            items.append(
                InvoiceLineItemResponse(
                    account_code=_str(it.get("accountCode")),
                    account_name=_str(it.get("accountName")),
                    booking_text=_str(it.get("bookingText")),
                    amount=_dec(it.get("amount")),
                    vat_amount=_dec(it.get("vatAmount")),
                    vat_percentage=_dec(it.get("vatPercentage")),
                )
            )

    order_required = data.get("orderRequired")
    if not isinstance(order_required, bool):
        order_required = None
    order_day_offset = data.get("orderDayOffset")
    if not isinstance(order_day_offset, int):
        order_day_offset = None

    return InvoiceDetailResponse(
        invoice_number=_str(data.get("name")),
        issued_date=_date(data.get("issuedDate")),
        amount=_dec(data.get("amount")),
        state=_str(data.get("state")),
        counterpart_name=_str(data.get("counterpartContactName")),
        # Per Impower's nomenclature:
        #   counterpart* = recipient (vendor) — the bill is paid TO
        #   property*    = sender (WHV bank account) — the bill is paid FROM
        # The original code mis-mapped counterpart_iban to the
        # property side; corrected here so the dialog shows the
        # vendor's IBAN on the "Zum Konto" line and the property's
        # on the "Vom Konto" line.
        counterpart_iban=_str(data.get("orderCounterpartIban")),
        counterpart_bic=_str(data.get("orderCounterpartBic")),
        property_iban=_str(data.get("orderPropertyIban")),
        property_bic=_str(data.get("orderPropertyBic")),
        order_required=order_required,
        order_statement=_str(data.get("orderStatement")),
        order_day_offset=order_day_offset,
        items=items,
    )


@router.get(
    "/properties/{property_id}/folders",
    response_model=list[DocumentFolderResponse],
)
async def get_my_property_folders(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentFolderResponse]:
    """Read-only folder tree for the portal. Same 404-on-no-access
    behaviour as `/me/properties/{id}/documents` so we don't leak
    existence of a folder under a property the caller can't see."""
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    rows = (
        await session.scalars(
            select(DocumentFolder)
            .where(
                DocumentFolder.property_id == prop.id,
                DocumentFolder.deleted_at.is_(None),
            )
            .order_by(DocumentFolder.name)
        )
    ).all()
    return [DocumentFolderResponse.model_validate(f) for f in rows]


@router.get("/documents/{document_id}/file")
async def download_my_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Authenticated PDF download for portal users.

    Two scope checks for non-Verwalter callers: the document's property
    must be visible (same `_visible_properties_stmt` rule used elsewhere)
    AND the row-scope filter must allow it (so a Mieter on Unit 4 can't
    deep-link to a doc Impower pinned to Unit 1 on the same property).
    Verwalter sees everything.

    Source resolution (same order as the Celery extraction tasks'
    `_read_doc_bytes` helper):
      1. Local cache at `document_path(doc.id, suffix)` if storage_url
         carries the `local-disk:<suffix>` marker.
      2. Impower's `/documents/{impower_id}/download` endpoint, pulled
         on demand. Most owner-facing docs (Rechnungen, Abrechnungen)
         live ONLY on Impower's side until §1.4d iter 2 mirrors them
         to Hetzner OS — so falling back here is the common path, not
         the exception.
    """
    doc_stmt = select(Document).where(
        Document.id == document_id,
        Document.organization_id == current_user.organization_id,
        Document.deleted_at.is_(None),
    )
    if current_user.role != UserRole.VERWALTER:
        # Invoice-aware: lets an owner download a WEG vendor invoice
        # (RECHNUNG, no unit/contract pin); for every other kind this is
        # identical to the plain document filter (the RECHNUNG branch
        # can't match), so non-invoice downloads stay gated as before.
        doc_stmt = doc_stmt.where(_invoice_visibility_filter(current_user))
    doc = await session.scalar(doc_stmt)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Property-scope check (skipped for Verwalter — they see everything).
    if current_user.role != UserRole.VERWALTER and doc.property_id is not None:
        prop_stmt = _visible_properties_stmt(current_user).where(Property.id == doc.property_id)
        prop = await session.scalar(prop_stmt)
        if prop is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # Storno gate. The BYTES are the leak, not just the booking
        # detail: `_invoice_visibility_filter` admits every WEG vendor
        # RECHNUNG, so without this an owner downloads the PDF of a
        # cancelled invoice even while the list hides it and the detail
        # 404s. Same cached set the vendor list filters on, so the
        # download agrees with what the list showed.
        source_id = (doc.raw_jsonb or {}).get("sourceId")
        if (
            doc.kind == DocumentKind.RECHNUNG
            and isinstance(source_id, int)
            and prop.impower_id is not None
            and source_id in await get_reversed_invoice_cache().get(prop.impower_id, settings)
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    download_name = _safe_download_filename(doc.name, doc.mime_type, doc.storage_url)

    # 1. Local cache — fastest, no Impower round-trip.
    if doc.storage_url and doc.storage_url.startswith("local-disk:"):
        suffix = doc.storage_url[len("local-disk:") :]
        path = document_path(doc.id, suffix)
        if path.exists():
            return FileResponse(
                path,
                media_type=doc.mime_type or "application/octet-stream",
                filename=download_name,
            )
        # storage_url claimed local but the file's gone — log + fall
        # through to Impower so the user still gets the bytes.
        # (Caching back to disk is a §1.4d-iter-2 problem.)

    # 2. Impower on-demand fallback. Most Impower-imported docs land
    # here because we don't mirror their bytes yet.
    if doc.impower_id is not None and settings.impower_api_token:
        from app.integrations.impower.client import ImpowerClient, ImpowerError

        try:
            async with ImpowerClient(
                settings.impower_api_base, settings.impower_api_token
            ) as client:
                data = await client.download_document_content(int(doc.impower_id))
        except ImpowerError:
            # Impower 5xx / network — surface as 502 so the SPA shows
            # the upstream error instead of "file not found" (which
            # the user would interpret as our problem).
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Datei konnte nicht von Impower geladen werden.",
            ) from None
        if data is not None:
            return Response(
                content=data,
                media_type=doc.mime_type or "application/pdf",
                headers={
                    # RFC 6266 — using `filename=` (ASCII) plus
                    # `filename*=UTF-8'…` for umlauts in the Impower
                    # name. Browsers honor whichever they support.
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


def _safe_download_filename(name: str, mime_type: str | None, storage_url: str | None) -> str:
    """Build a sensible filename for the Content-Disposition header.

    Impower's `name` is usually descriptive ("R26/01384 …") but lacks
    an extension. We append one inferred from the MIME type or the
    local-disk suffix so the OS / browser opens the file with the
    right app instead of treating it as octet-stream.
    """
    has_extension = "." in name.rsplit("/", 1)[-1]
    if has_extension:
        return name
    if storage_url and storage_url.startswith("local-disk:"):
        return name + storage_url[len("local-disk:") :]
    # Most Impower docs are PDFs; the mime check covers the rest.
    if mime_type == "application/pdf":
        return name + ".pdf"
    if mime_type and "/" in mime_type:
        return name + "." + mime_type.split("/", 1)[1]
    return name + ".pdf"


def _ascii_fallback(s: str) -> str:
    """Strip non-ASCII chars for the legacy `filename=` Content-
    Disposition slot. The `filename*=` slot carries the real UTF-8
    name; this is just the safe fallback for old clients."""
    return "".join(ch if ord(ch) < 128 else "_" for ch in s)


def _rfc5987(s: str) -> str:
    """Percent-encode for the `filename*=UTF-8''…` Content-Disposition
    slot per RFC 5987. Same semantics as urllib.parse.quote with a
    conservative safe-char set."""
    from urllib.parse import quote

    return quote(s, safe="")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete the current user. Spec §7.3: 30-day recovery window.

    Effect:
    - users.deleted_at = now (auth dependency rejects further requests)
    - All non-revoked sessions for this user → revoked_at = now (refresh tokens dead)
    - Audit row written
    - One commit, all-or-nothing

    Hard-delete after the 30-day window is a future operational job
    (not implemented in v1 of this endpoint).
    """
    now = datetime.now(UTC)

    current_user.deleted_at = now

    await session.execute(
        update(DbSession)
        .where(DbSession.user_id == current_user.id, DbSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="user_self_delete",
            target_type="users",
            target_id=str(current_user.id),
        )
    )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export")
async def export_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    """DSGVO Art. 20 (portability) — return the user's personal data as JSON.

    Includes only data *about the user*: their profile, their sessions
    (metadata, never the token hashes), and audit entries where they were
    the actor. Organizational data (properties, documents, contacts they
    have *access* to) is intentionally out of scope — it's not their
    personal data under GDPR.
    """
    sessions = (
        await session.scalars(
            select(DbSession)
            .where(DbSession.user_id == current_user.id)
            .order_by(DbSession.created_at.desc())
        )
    ).all()

    audit_rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.actor_user_id == current_user.id)
            .order_by(AuditLog.created_at.desc())
        )
    ).all()

    payload: dict[str, object] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "format_version": "1.0",
        "user": {
            "id": str(current_user.id),
            "organization_id": str(current_user.organization_id),
            "email": current_user.email,
            "role": current_user.role.value,
            "contact_id_impower": current_user.contact_id_impower,
            "locale": current_user.locale,
            "last_login_at": (
                current_user.last_login_at.isoformat() if current_user.last_login_at else None
            ),
            "created_at": current_user.created_at.isoformat(),
            "updated_at": current_user.updated_at.isoformat(),
            "deleted_at": (
                current_user.deleted_at.isoformat() if current_user.deleted_at else None
            ),
            # password_hash, sign_in_with_apple_sub, mfa_secret intentionally omitted.
        },
        "sessions": [
            {
                "id": str(s.id),
                "expires_at": s.expires_at.isoformat(),
                "user_agent": s.user_agent,
                "ip_hash": s.ip_hash,
                "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
                "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
                "created_at": s.created_at.isoformat(),
                # refresh_token_hash intentionally omitted.
            }
            for s in sessions
        ],
        "audit_log_entries": [
            {
                "id": str(a.id),
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "payload": a.payload_json,
                "created_at": a.created_at.isoformat(),
            }
            for a in audit_rows
        ],
    }

    filename = f"whv-export-{current_user.id}-{datetime.now(UTC).date().isoformat()}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# selectinload import is kept for future N+1 mitigation; silence unused-import.
_ = selectinload
