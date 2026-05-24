import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.db import get_session
from app.models import Contact, Contract, ContractContact, Document, Property, Unit, User, UserRole
from app.schemas.auth import UserResponse
from app.schemas.document import DocumentResponse
from app.schemas.property import PropertyDetailResponse, PropertyResponse
from app.schemas.unit import UnitResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role.value,
        organization_id=current_user.organization_id,
        contact_id_impower=current_user.contact_id_impower,
    )


def _visible_properties_stmt(user: User):  # type: ignore[no-untyped-def]
    """Build a SELECT statement for properties visible to the given user.

    VERWALTER sees all org properties; other roles are scoped via
    contact_id_impower → contract_contacts → contracts → properties.
    """
    base = select(Property).where(
        Property.organization_id == user.organization_id,
        Property.deleted_at.is_(None),
    )
    if user.role == UserRole.VERWALTER:
        return base
    return (
        base.join(Contract, Contract.property_id == Property.id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(Contact.impower_id == user.contact_id_impower)
        .distinct()
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

    return PropertyDetailResponse(
        **PropertyResponse.model_validate(prop).model_dump(),
        units=[UnitResponse.model_validate(u) for u in unit_rows],
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

    doc_rows = (
        await session.scalars(
            select(Document)
            .where(Document.property_id == prop.id, Document.deleted_at.is_(None))
            .order_by(Document.issued_date.desc().nulls_last(), Document.name)
        )
    ).all()

    return [DocumentResponse.model_validate(d) for d in doc_rows]


# selectinload import is kept for future N+1 mitigation; silence unused-import.
_ = selectinload
