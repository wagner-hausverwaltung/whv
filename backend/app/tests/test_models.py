import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    ContractType,
    Document,
    DocumentKind,
    DocumentVisibility,
    InviteCode,
    Organization,
    PreferredChannel,
    Property,
    PropertyState,
    PropertyType,
    Unit,
    UnitType,
    User,
    UserRole,
)


async def test_organization_round_trip(session: AsyncSession) -> None:
    org = Organization(name="Round Trip GmbH")
    session.add(org)
    await session.flush()
    assert isinstance(org.id, uuid.UUID)
    assert org.created_at is not None
    assert org.updated_at is not None


async def test_full_master_data_graph(session: AsyncSession) -> None:
    org = Organization(name="Graph Test GmbH")
    session.add(org)
    await session.flush()

    prop = Property(
        organization_id=org.id,
        impower_id=1001,
        name="Schillerstraße 12, Stuttgart",
        type=PropertyType.STRATA,
        state=PropertyState.READY,
        city="Stuttgart",
        street="Schillerstraße",
        number="12",
        postal_code="70173",
        country="DE",
    )
    session.add(prop)
    await session.flush()

    unit = Unit(
        organization_id=org.id,
        impower_id=2001,
        property_id=prop.id,
        unit_hr_id="W01",
        type=UnitType.APARTMENT,
        floor="EG",
        is_owned_by_weg=False,
        voting_share=Decimal("125.500000"),
        area_m2=Decimal("78.40"),
        rooms=Decimal("3.5"),
    )
    session.add(unit)
    await session.flush()

    contact = Contact(
        organization_id=org.id,
        impower_id=3001,
        kind=ContactKind.PERSON,
        first_name="Anna",
        last_name="Schmidt",
        email="anna@example.com",
        phone="+49 711 1234567",
        preferred_channel=PreferredChannel.EMAIL,
    )
    session.add(contact)
    await session.flush()

    contract = Contract(
        organization_id=org.id,
        impower_id=4001,
        property_id=prop.id,
        unit_id=unit.id,
        type=ContractType.OWNER,
        contract_number="2024-001",
        is_vacant=False,
    )
    session.add(contract)
    await session.flush()

    session.add(ContractContact(contract_id=contract.id, contact_id=contact.id, role="primary"))
    await session.flush()

    doc = Document(
        organization_id=org.id,
        impower_id=5001,
        property_id=prop.id,
        contract_id=contract.id,
        name="Jahresabrechnung 2024.pdf",
        kind=DocumentKind.JAHRESABRECHNUNG,
        mime_type="application/pdf",
        size_bytes=1234567,
    )
    session.add(doc)
    await session.flush()

    fetched_prop = await session.scalar(select(Property).where(Property.impower_id == 1001))
    assert fetched_prop is not None
    assert fetched_prop.type == PropertyType.STRATA
    assert fetched_prop.city == "Stuttgart"

    fetched_unit = await session.scalar(select(Unit).where(Unit.impower_id == 2001))
    assert fetched_unit is not None
    assert fetched_unit.voting_share == Decimal("125.500000")

    fetched_doc = await session.scalar(select(Document).where(Document.impower_id == 5001))
    assert fetched_doc is not None
    assert fetched_doc.kind == DocumentKind.JAHRESABRECHNUNG
    assert fetched_doc.visibility == DocumentVisibility.PRIVATE  # server default

    junction = await session.scalar(
        select(ContractContact).where(ContractContact.contract_id == contract.id)
    )
    assert junction is not None
    assert junction.role == "primary"


async def test_user_and_invite_code(session: AsyncSession) -> None:
    org = Organization(name="Auth Test GmbH")
    session.add(org)
    await session.flush()

    user = User(
        organization_id=org.id,
        email="luis@example.com",
        role=UserRole.VERWALTER,
        locale="de",
    )
    session.add(user)
    await session.flush()
    assert user.role == UserRole.VERWALTER

    code = InviteCode(
        organization_id=org.id,
        code="ABCD1234",
        email="newowner@example.com",
        role=UserRole.EIGENTUEMER,
        expires_at=datetime.now(UTC) + timedelta(days=14),
        created_by=user.id,
        scope_json={"property_ids": [str(uuid.uuid4())]},
    )
    session.add(code)
    await session.flush()

    fetched = await session.scalar(select(InviteCode).where(InviteCode.code == "ABCD1234"))
    assert fetched is not None
    assert fetched.role == UserRole.EIGENTUEMER
    assert fetched.consumed_at is None


async def test_soft_delete_sets_timestamp(session: AsyncSession) -> None:
    org = Organization(name="Soft Delete GmbH")
    session.add(org)
    await session.flush()

    contact = Contact(
        organization_id=org.id,
        kind=ContactKind.COMPANY,
        company_name="Klempnerei Müller GmbH",
        vat_id="DE123456789",
    )
    session.add(contact)
    await session.flush()
    assert contact.deleted_at is None

    contact.deleted_at = datetime.now(UTC)
    await session.flush()
    fetched = await session.scalar(select(Contact).where(Contact.id == contact.id))
    assert fetched is not None
    assert fetched.deleted_at is not None
