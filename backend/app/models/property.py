import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import (
    OrganizationScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7_pk,
)


class PropertyType(enum.StrEnum):
    OWNER = "OWNER"
    RENTAL = "RENTAL"
    STRATA = "STRATA"


class PropertyState(enum.StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    DISABLED = "DISABLED"


class Property(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    impower_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    property_hr_id: Mapped[str | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[PropertyType] = mapped_column(
        Enum(PropertyType, name="property_type"), nullable=False
    )
    state: Mapped[PropertyState] = mapped_column(
        Enum(PropertyState, name="property_state"), nullable=False
    )

    city: Mapped[str | None] = mapped_column(nullable=True)
    street: Mapped[str | None] = mapped_column(nullable=True)
    number: Mapped[str | None] = mapped_column(nullable=True)
    postal_code: Mapped[str | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(nullable=True)

    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Verwalter-uploaded hero photo of the building/property. None until the
    # admin uploads one; served by the static mount at /admin/property-images/.
    # Pillow normalises every upload to a PNG under settings.property_image_dir,
    # keyed by property id. Same pattern as user avatars.
    image_url: Mapped[str | None] = mapped_column(nullable=True)
    # Geocoded once from the postal address (scripts/geocode_properties.py);
    # the phone uses these to suggest the destination property of a trip.
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    __table_args__ = (Index("ix_properties_org_state", "organization_id", "state"),)


class Building(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "buildings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    impower_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    name: Mapped[str | None] = mapped_column(nullable=True)

    city: Mapped[str | None] = mapped_column(nullable=True)
    street: Mapped[str | None] = mapped_column(nullable=True)
    number: Mapped[str | None] = mapped_column(nullable=True)
    postal_code: Mapped[str | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(nullable=True)

    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
