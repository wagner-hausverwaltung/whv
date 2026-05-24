import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import (
    OrganizationScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7_pk,
)


class ContactKind(enum.StrEnum):
    PERSON = "PERSON"
    COMPANY = "COMPANY"


class PreferredChannel(enum.StrEnum):
    PORTAL = "PORTAL"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    EPOST = "EPOST"


class Contact(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    impower_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    kind: Mapped[ContactKind] = mapped_column(
        Enum(ContactKind, name="contact_kind"), nullable=False
    )

    # Person fields
    salutation: Mapped[str | None] = mapped_column(nullable=True)
    title: Mapped[str | None] = mapped_column(nullable=True)
    first_name: Mapped[str | None] = mapped_column(nullable=True)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Company fields
    company_name: Mapped[str | None] = mapped_column(nullable=True)
    vat_id: Mapped[str | None] = mapped_column(nullable=True)
    trade_register_number: Mapped[str | None] = mapped_column(nullable=True)

    # Common
    recipient_name: Mapped[str | None] = mapped_column(nullable=True)
    mandate_number: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    additional_contacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Address
    city: Mapped[str | None] = mapped_column(nullable=True)
    street: Mapped[str | None] = mapped_column(nullable=True)
    number: Mapped[str | None] = mapped_column(nullable=True)
    postal_code: Mapped[str | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(nullable=True)

    preferred_channel: Mapped[PreferredChannel] = mapped_column(
        Enum(PreferredChannel, name="preferred_channel"),
        nullable=False,
        server_default=text("'EMAIL'"),
    )

    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactBankAccount(TimestampMixin, Base):
    __tablename__ = "contact_bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    iban: Mapped[str | None] = mapped_column(nullable=True)
    bic: Mapped[str | None] = mapped_column(nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(nullable=True)
