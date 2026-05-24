from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session
from app.models import Contact, Contract, ContractContact, Property, User, UserRole
from app.schemas.auth import UserResponse
from app.schemas.property import PropertyResponse

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


@router.get("/properties", response_model=list[PropertyResponse])
async def get_my_properties(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PropertyResponse]:
    if current_user.role == UserRole.VERWALTER:
        stmt = (
            select(Property)
            .where(
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
            )
            .order_by(Property.name)
        )
    else:
        if current_user.contact_id_impower is None:
            return []
        stmt = (
            select(Property)
            .join(Contract, Contract.property_id == Property.id)
            .join(ContractContact, ContractContact.contract_id == Contract.id)
            .join(Contact, Contact.id == ContractContact.contact_id)
            .where(
                Contact.impower_id == current_user.contact_id_impower,
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
            )
            .distinct()
            .order_by(Property.name)
        )

    rows = (await session.scalars(stmt)).all()
    return [PropertyResponse.model_validate(p) for p in rows]
