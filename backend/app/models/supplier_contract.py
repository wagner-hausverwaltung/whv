"""SupplierContract (Versorgungsvertrag) — a WEG's supply/service contracts.

Insurance, electricity, gas, waste, chimney sweep, elevator maintenance etc.
per property, with term + pricing metadata and an optional link to the meter
the contract bills against (Strom/Gas/Wasser). NOT to be confused with
:class:`app.models.contract.Contract`, which is the Impower-synced unit
occupancy contract (OWNER/TENANT).

``category`` / ``price_period`` are free-form Text columns (evolvable without
a pg-enum migration); the StrEnums below are the canonical sets used in code —
same pattern as OfferInquiry.status.
"""

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, SoftDeleteMixin, TimestampMixin, uuid7_pk


class SupplierContractCategory(enum.StrEnum):
    VERSICHERUNG = "VERSICHERUNG"
    STROM = "STROM"
    GAS = "GAS"
    HEIZOEL = "HEIZOEL"
    WASSER_ABWASSER = "WASSER_ABWASSER"
    MUELL = "MUELL"
    GRUNDBESITZABGABEN = "GRUNDBESITZABGABEN"
    MESSDIENST = "MESSDIENST"
    SCHORNSTEINFEGER = "SCHORNSTEINFEGER"
    HEIZUNG_WARTUNG = "HEIZUNG_WARTUNG"
    AUFZUG = "AUFZUG"
    HAUSMEISTER = "HAUSMEISTER"
    REINIGUNG = "REINIGUNG"
    GARTEN = "GARTEN"
    WINTERDIENST = "WINTERDIENST"
    KABEL_INTERNET = "KABEL_INTERNET"
    BANK = "BANK"
    SONSTIGES = "SONSTIGES"


class SupplierContractPricePeriod(enum.StrEnum):
    MONATLICH = "MONATLICH"
    JAEHRLICH = "JAEHRLICH"


class SupplierContractStatus(enum.StrEnum):
    """Manual lifecycle status the Verwalter tracks — a cancelled contract
    must stop screaming red for a 'missed' Kündigungsfrist."""

    AKTIV = "AKTIV"
    GEKUENDIGT = "GEKUENDIGT"
    BEENDET = "BEENDET"


class SupplierContract(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "supplier_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=SupplierContractStatus.AKTIV.value,
        server_default=SupplierContractStatus.AKTIV.value,
    )
    # Optional link to the Dienstleister contact behind the provider.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    contract_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which meter the contract bills against (Strom/Gas/Wasser) — surfaces the
    # Zählernummer/Marktlokation metadata without duplicating it here.
    meter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meters.id", ondelete="SET NULL"), nullable=True
    )

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_renew: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_period: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_supplier_contracts_org_category", "organization_id", "category"),)
