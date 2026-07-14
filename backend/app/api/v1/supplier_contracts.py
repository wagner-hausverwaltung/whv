"""Versorgungsverträge (supplier contracts) — Verwalter-only admin endpoints.

A WEG's supply/service contracts (Versicherung, Strom, Gas, Müll, …) with
term + pricing metadata. Distinct from the Impower-synced unit occupancy
contracts (/admin/contracts).

  GET    /admin/supplier-contracts                          org-wide board
  GET    /admin/properties/{property_id}/supplier-contracts per-Objekt list
  POST   /admin/properties/{property_id}/supplier-contracts create
  PUT    /admin/supplier-contracts/{contract_id}            update
  DELETE /admin/supplier-contracts/{contract_id}            soft delete
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session
from app.models import (
    AuditLog,
    Contact,
    Document,
    Meter,
    Property,
    SupplierContract,
    User,
    UserRole,
)
from app.schemas.supplier_contract import (
    SupplierContractBody,
    SupplierContractDocumentItem,
    SupplierContractResponse,
)

admin_router = APIRouter(prefix="/admin", tags=["supplier-contracts"])

_verwalter_only = require_role(UserRole.VERWALTER)


async def _property_or_404(session: AsyncSession, user: User, property_id: uuid.UUID) -> Property:
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liegenschaft not found")
    return prop


async def _contract_or_404(
    session: AsyncSession, user: User, contract_id: uuid.UUID
) -> SupplierContract:
    contract = await session.scalar(
        select(SupplierContract).where(
            SupplierContract.id == contract_id,
            SupplierContract.organization_id == user.organization_id,
            SupplierContract.deleted_at.is_(None),
        )
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vertrag not found")
    return contract


async def _validate_links(
    session: AsyncSession, user: User, property_id: uuid.UUID, body: SupplierContractBody
) -> None:
    """The linked meter must belong to the SAME property; the contact to the org."""
    if body.meter_id is not None:
        meter = await session.scalar(
            select(Meter).where(
                Meter.id == body.meter_id,
                Meter.organization_id == user.organization_id,
                Meter.property_id == property_id,
            )
        )
        if meter is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zähler gehört nicht zu dieser Liegenschaft.",
            )
    if body.contact_id is not None:
        contact = await session.scalar(
            select(Contact).where(
                Contact.id == body.contact_id,
                Contact.organization_id == user.organization_id,
                Contact.deleted_at.is_(None),
            )
        )
        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Kontakt nicht gefunden."
            )


def _apply(contract: SupplierContract, body: SupplierContractBody) -> None:
    contract.category = body.category
    contract.provider_name = body.provider_name.strip()
    contract.status = body.status
    contract.contact_id = body.contact_id
    contract.contract_number = (body.contract_number or "").strip() or None
    contract.customer_number = (body.customer_number or "").strip() or None
    contract.meter_id = body.meter_id
    contract.start_date = body.start_date
    contract.end_date = body.end_date
    contract.cancellation_months = body.cancellation_months
    contract.auto_renew = body.auto_renew
    contract.price = body.price
    contract.price_period = body.price_period
    contract.notes = (body.notes or "").strip() or None


def _audit(user: User, action: str, contract: SupplierContract) -> AuditLog:
    return AuditLog(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action=action,
        target_type="supplier_contracts",
        target_id=str(contract.id),
        payload_json={
            "category": contract.category,
            "provider_name": contract.provider_name,
            "property_id": str(contract.property_id),
        },
    )


async def _to_responses(
    session: AsyncSession, contracts: list[SupplierContract]
) -> list[SupplierContractResponse]:
    """Attach the display conveniences (property name, meter number, linked
    Dienstleister contact)."""
    prop_ids = {c.property_id for c in contracts}
    meter_ids = {c.meter_id for c in contracts if c.meter_id is not None}
    contact_ids = {c.contact_id for c in contracts if c.contact_id is not None}
    prop_names: dict[uuid.UUID, str] = {}
    meter_numbers: dict[uuid.UUID, str] = {}
    contact_info: dict[uuid.UUID, tuple[str, str | None, str | None]] = {}
    if prop_ids:
        rows = await session.execute(
            select(Property.id, Property.name).where(Property.id.in_(prop_ids))
        )
        prop_names = {pid: name for pid, name in rows.all()}
    if meter_ids:
        rows = await session.execute(
            select(Meter.id, Meter.meter_number).where(Meter.id.in_(meter_ids))
        )
        meter_numbers = {mid: num for mid, num in rows.all()}
    if contact_ids:
        rows = await session.execute(
            select(
                Contact.id,
                Contact.company_name,
                Contact.first_name,
                Contact.last_name,
                Contact.email,
                Contact.phone,
            ).where(Contact.id.in_(contact_ids))
        )
        for cid, company, first, last, email, phone in rows.all():
            name = company or " ".join(p for p in (first, last) if p) or "—"
            contact_info[cid] = (name, email, phone)
    out: list[SupplierContractResponse] = []
    for c in contracts:
        resp = SupplierContractResponse.model_validate(c)
        resp.property_name = prop_names.get(c.property_id)
        resp.meter_number = meter_numbers.get(c.meter_id) if c.meter_id else None
        if c.contact_id and c.contact_id in contact_info:
            resp.contact_name, resp.contact_email, resp.contact_phone = contact_info[c.contact_id]
        out.append(resp)
    return out


# Legal-form / filler tokens that don't identify a provider in doc names.
_PROVIDER_STOPWORDS = {
    "gmbh",
    "ag",
    "kg",
    "co",
    "gbr",
    "ohg",
    "holding",
    "und",
    "der",
    "die",
    "das",
    "von",
    "durch",
    "im",
    "auftrag",
    "service",
    "services",
    "vertrieb",
    "west",
    "deutschland",
    "energie",
    "baden-württemberg",
    "generalvertretung",
    "generalagentur",
    "versicherungsmakler",
    "landeshauptstadt",
}


def _provider_tokens(provider: str) -> list[str]:
    tokens = [
        t
        for t in re.split(r"[^\wäöüß+-]+", provider.lower())
        if len(t) >= 4 and t not in _PROVIDER_STOPWORDS
    ]
    # Longest tokens are the most distinctive ("sparkassenversicherung").
    return sorted(tokens, key=len, reverse=True)[:3]


@admin_router.get("/supplier-contracts", response_model=list[SupplierContractResponse])
async def admin_list_all_supplier_contracts(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SupplierContractResponse]:
    """Org-wide board: every property's supplier contracts, soonest-ending
    first (NULL end dates last), so expiring contracts surface on top."""
    contracts = list(
        (
            await session.scalars(
                select(SupplierContract)
                .where(
                    SupplierContract.organization_id == current_user.organization_id,
                    SupplierContract.deleted_at.is_(None),
                )
                .order_by(
                    SupplierContract.end_date.asc().nulls_last(),
                    SupplierContract.provider_name.asc(),
                )
            )
        ).all()
    )
    return await _to_responses(session, contracts)


@admin_router.get(
    "/properties/{property_id}/supplier-contracts",
    response_model=list[SupplierContractResponse],
)
async def admin_list_property_supplier_contracts(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SupplierContractResponse]:
    await _property_or_404(session, current_user, property_id)
    contracts = list(
        (
            await session.scalars(
                select(SupplierContract)
                .where(
                    SupplierContract.property_id == property_id,
                    SupplierContract.organization_id == current_user.organization_id,
                    SupplierContract.deleted_at.is_(None),
                )
                .order_by(SupplierContract.category.asc(), SupplierContract.provider_name.asc())
            )
        ).all()
    )
    return await _to_responses(session, contracts)


@admin_router.post(
    "/properties/{property_id}/supplier-contracts",
    response_model=SupplierContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_supplier_contract(
    property_id: uuid.UUID,
    body: SupplierContractBody,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupplierContractResponse:
    await _property_or_404(session, current_user, property_id)
    await _validate_links(session, current_user, property_id, body)
    contract = SupplierContract(
        organization_id=current_user.organization_id, property_id=property_id, category=""
    )
    _apply(contract, body)
    session.add(contract)
    await session.flush()
    session.add(_audit(current_user, "supplier_contract_created", contract))
    await session.commit()
    await session.refresh(contract)
    return (await _to_responses(session, [contract]))[0]


@admin_router.put("/supplier-contracts/{contract_id}", response_model=SupplierContractResponse)
async def admin_update_supplier_contract(
    contract_id: uuid.UUID,
    body: SupplierContractBody,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupplierContractResponse:
    contract = await _contract_or_404(session, current_user, contract_id)
    await _validate_links(session, current_user, contract.property_id, body)
    _apply(contract, body)
    session.add(_audit(current_user, "supplier_contract_updated", contract))
    await session.commit()
    await session.refresh(contract)
    return (await _to_responses(session, [contract]))[0]


@admin_router.get(
    "/supplier-contracts/{contract_id}/documents",
    response_model=list[SupplierContractDocumentItem],
)
async def admin_supplier_contract_documents(
    contract_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SupplierContractDocumentItem]:
    """The contract's latest Belege (newest first, max 5): documents on the
    same property from the linked contact, or — when no contact is linked —
    whose vendor/name matches the provider. Download via the existing
    GET /admin/documents/{id}/file."""
    contract = await _contract_or_404(session, current_user, contract_id)
    conds = []
    if contract.contact_id is not None:
        # A linked contact is authoritative — no fuzzy fallback, so a
        # "Stadt Ditzingen" Bescheid never shows up under "Stadtwerke".
        conds.append(Document.contact_id == contract.contact_id)
    else:
        haystack = func.lower(
            func.coalesce(Contact.company_name, "")
            + " "
            + func.coalesce(Contact.first_name, "")
            + " "
            + func.coalesce(Contact.last_name, "")
            + " "
            + Document.name
        )
        tokens = _provider_tokens(contract.provider_name)
        if tokens:
            # EVERY token must appear as a whole word ("stadt" must not
            # substring-match "Stadtwerke") — keeps city-name collisions out.
            conds.append(and_(*[haystack.op("~")(rf"\m{re.escape(t)}\M") for t in tokens]))
    if not conds:
        return []
    rows = await session.execute(
        select(Document.id, Document.name, Document.issued_date, Document.amount)
        .join(Contact, Contact.id == Document.contact_id, isouter=True)
        .where(
            Document.organization_id == current_user.organization_id,
            Document.property_id == contract.property_id,
            Document.deleted_at.is_(None),
            or_(*conds),
        )
        .order_by(
            Document.issued_date.desc().nulls_last(), Document.uploaded_at.desc().nulls_last()
        )
        .limit(5)
    )
    return [
        SupplierContractDocumentItem(id=i, name=n, issued_date=d, amount=a)
        for i, n, d, a in rows.all()
    ]


@admin_router.delete("/supplier-contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_supplier_contract(
    contract_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    contract = await _contract_or_404(session, current_user, contract_id)
    contract.deleted_at = datetime.now(UTC)
    session.add(_audit(current_user, "supplier_contract_deleted", contract))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
