import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import (
    OrganizationScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7_pk,
)


class UnitType(enum.StrEnum):
    APARTMENT = "APARTMENT"
    PARKING = "PARKING"
    OTHER = "OTHER"
    COMMERCIAL = "COMMERCIAL"


class Unit(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    impower_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buildings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_hr_id: Mapped[str | None] = mapped_column(nullable=True)
    type: Mapped[UnitType] = mapped_column(Enum(UnitType, name="unit_type"), nullable=False)
    floor: Mapped[str | None] = mapped_column(nullable=True)
    position: Mapped[str | None] = mapped_column(nullable=True)
    unit_rank: Mapped[int | None] = mapped_column(nullable=True)
    is_owned_by_weg: Mapped[bool | None] = mapped_column(nullable=True)
    voting_share: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Heizfläche — usable heating floor area, often differs from
    # area_m2 (terraces, cellars excluded). Sourced manually from
    # Impower's "Eigenschaften der Einheiten" panel (their REST API
    # doesn't expose it) until a sync path opens.
    heated_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Personen — registered occupant head-count used for cost
    # distribution. Numeric not Integer because Impower stores 0.5
    # partials for shared apartments. Same manual-fill story as
    # heated_area_m2.
    persons: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    rooms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)

    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
