"""Jahresabrechnung progress tracker (per Objekt, per Wirtschaftsjahr).

Digitises the paper Kanban: each property's annual-accounting cycle is tracked
through the 9 fixed stages A-I. v1 is an all-manual checklist (Verwalter ticks
stages; owners get a read-only progress view) — auto-signals (Zähler/Dokumente/
ETV) + ad-hoc todos come in later phases.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk

# The fixed pipeline (code → German label). Ordered A-I; the order is the
# display order. Data, not config — a label change is a one-liner here.
ACCOUNTING_STAGES: list[tuple[str, str]] = [
    ("A", "Zählerstände gemeldet"),
    ("B", "Rechnungen Energieversorger vorhanden"),
    ("C", "Kostenaufstellung erstellt und versendet"),
    ("D", "Kostenaufstellung eingegangen"),
    ("E", "Abrechnung erstellt"),
    ("F", "Abrechnung geprüft"),
    ("G", "Abrechnung versendet"),
    ("H", "Eigentümerversammlung geplant"),
    ("I", "Eigentümerversammlung erledigt / Protokoll versendet"),
]
ACCOUNTING_STAGE_CODES = [c for c, _ in ACCOUNTING_STAGES]
ACCOUNTING_STAGE_LABELS = dict(ACCOUNTING_STAGES)


class AccountingCycle(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "accounting_cycles"
    __table_args__ = (
        UniqueConstraint("property_id", "year", name="uq_accounting_cycle_property_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The Wirtschaftsjahr being settled (e.g. 2025).
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    stages: Mapped[list["AccountingCycleStage"]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )


class AccountingCycleStage(Base):
    __tablename__ = "accounting_cycle_stages"
    __table_args__ = (
        UniqueConstraint("cycle_id", "stage_code", name="uq_accounting_stage_cycle_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_code: Mapped[str] = mapped_column(Text, nullable=False)  # "A" … "I"
    done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Free-text note, visible to owners too (the tracker is fully read-visible).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    cycle: Mapped[AccountingCycle] = relationship(back_populates="stages")
