"""Test helpers that create DB rows committed against the test engine.

Each helper picks unique strings (UUID-suffixed) so tests can run serially
without colliding, even though they share the same database.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.passwords import hash_password
from app.models import (
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    ContractType,
    Document,
    DocumentKind,
    InviteCode,
    Organization,
    Property,
    PropertyState,
    PropertyType,
    Unit,
    UnitType,
    User,
    UserRole,
)


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


async def make_org(engine: AsyncEngine) -> Organization:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        org = Organization(name=f"Test Org {_short_id()}")
        s.add(org)
        await s.commit()
        await s.refresh(org)
    return org


async def make_invite(
    engine: AsyncEngine,
    *,
    org: Organization | None = None,
    role: UserRole = UserRole.VERWALTER,
    contact_id_impower: int | None = None,
    expires_in_days: int = 14,
    consumed: bool = False,
) -> tuple[InviteCode, Organization]:
    if org is None:
        org = await make_org(engine)
    code = _short_id().upper()
    email = f"user-{_short_id()}@test.de"
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        invite = InviteCode(
            organization_id=org.id,
            code=code,
            email=email,
            role=role,
            contact_id_impower=contact_id_impower,
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
            consumed_at=datetime.now(UTC) if consumed else None,
        )
        s.add(invite)
        await s.commit()
    return invite, org


async def make_user(
    engine: AsyncEngine,
    *,
    org: Organization | None = None,
    role: UserRole = UserRole.VERWALTER,
    contact_id_impower: int | None = None,
    password: str = "testing-pw-1234",
) -> tuple[User, str, str]:
    """Returns (user, email, password)."""
    if org is None:
        org = await make_org(engine)
    email = f"user-{_short_id()}@test.de"
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        user = User(
            organization_id=org.id,
            email=email,
            password_hash=hash_password(password),
            role=role,
            contact_id_impower=contact_id_impower,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
    return user, email, password


async def make_property(
    engine: AsyncEngine,
    *,
    org: Organization,
    name: str | None = None,
    impower_id: int | None = None,
) -> Property:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        prop = Property(
            organization_id=org.id,
            name=name or f"Test Property {_short_id()}",
            type=PropertyType.STRATA,
            state=PropertyState.READY,
            city="Stuttgart",
            impower_id=impower_id,
        )
        s.add(prop)
        await s.commit()
        await s.refresh(prop)
    return prop


async def make_unit(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    unit_hr_id: str | None = None,
    unit_type: UnitType = UnitType.APARTMENT,
    floor: str | None = "EG",
) -> Unit:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        unit = Unit(
            organization_id=org.id,
            property_id=prop.id,
            unit_hr_id=unit_hr_id or f"U-{_short_id()}",
            type=unit_type,
            floor=floor,
        )
        s.add(unit)
        await s.commit()
        await s.refresh(unit)
    return unit


async def make_document(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    name: str | None = None,
    kind: "DocumentKind | None" = None,
    unit: "Unit | None" = None,
    contract: "Contract | None" = None,
    contact: "Contact | None" = None,
) -> "Document":
    from app.models import Document as _Document
    from app.models import DocumentKind as _DocumentKind

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        doc = _Document(
            organization_id=org.id,
            property_id=prop.id,
            unit_id=unit.id if unit is not None else None,
            contract_id=contract.id if contract is not None else None,
            contact_id=contact.id if contact is not None else None,
            name=name or f"Test Doc {_short_id()}.pdf",
            kind=kind or _DocumentKind.SONSTIGES,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
    return doc


async def make_contact_with_contract_link(
    engine: AsyncEngine,
    *,
    org: Organization,
    prop: Property,
    contact_impower_id: int,
    unit: Unit | None = None,
    contract_type: ContractType = ContractType.OWNER,
    end_date: date | None = None,
    contract_impower_id: int | None = None,
    contact_email: str | None = None,
) -> tuple[Contact, Contract]:
    """Wires up a Contact (with impower_id) → Contract → Property via the junction table.

    Used to test EIGENTUEMER scope on /me/properties. Pass `unit` to
    pin the contract to a specific unit (drives the unit-scope branch of
    the document visibility filter, which checks for contracts the
    caller is on that target the doc's unit).
    """
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        contact = Contact(
            organization_id=org.id,
            impower_id=contact_impower_id,
            kind=ContactKind.PERSON,
            first_name="Test",
            last_name=f"Eigentuemer-{_short_id()}",
            email=contact_email,
        )
        s.add(contact)
        await s.flush()
        contract = Contract(
            organization_id=org.id,
            property_id=prop.id,
            unit_id=unit.id if unit is not None else None,
            type=contract_type,
            end_date=end_date,
            impower_id=contract_impower_id,
        )
        s.add(contract)
        await s.flush()
        s.add(ContractContact(contract_id=contract.id, contact_id=contact.id))
        await s.commit()
        await s.refresh(contact)
        await s.refresh(contract)
    return contact, contract
