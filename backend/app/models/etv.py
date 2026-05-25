"""Eigentümerversammlung (ETV) — in-person owner assembly tables.

Counterpart to `circular_resolutions`. An ETV is a scheduled meeting
with an agenda (Tagesordnung), per-TOP voting where applicable, free-
form discussion notes, and a signed PDF protocol uploaded after the
fact.

Three tables, each strictly nested under the previous one:

  EtvAssembly         — header (title, location, when, status, protocol)
    └── EtvAgendaItem — one row per Tagesordnungspunkt
          └── EtvDiscussionEntry — discussion contribution under that TOP

Beschluss tallies live on the agenda item itself (not in a separate
votes table) because for an in-person assembly the SIGNED PROTOCOL is
the authoritative record, not the click stream. The yes/no/abstain
integers + optional quorum + final result are what the Verwalter
transcribes from the protocol.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import (
    OrganizationScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7_pk,
)


class AssemblyStatus(enum.StrEnum):
    """Lifecycle of a single ETV — moved manually by the Verwalter.

    The owner-portal queue groups GEPLANT + EINGELADEN as "upcoming"
    and ABGEHALTEN as "past"; ABGESAGT shows up only in the admin
    view (the cancelled ones aren't useful to owners).
    """

    GEPLANT = "GEPLANT"        # date scheduled, invitations not yet sent
    EINGELADEN = "EINGELADEN"  # invitations dispatched, agenda locked
    ABGEHALTEN = "ABGEHALTEN"  # assembly happened, protocol on the way / uploaded
    ABGESAGT = "ABGESAGT"      # cancelled before it took place


class AgendaItemType(enum.StrEnum):
    """What a TOP is for. Drives the UI's per-row affordances:

    INFORMATION — Verwalter announces something, no vote, no discussion log
                  required.
    BESCHLUSS   — a vote was held; tally + optional quorum + result apply.
    DISKUSSION  — open discussion, no vote; we expect 1+ DiscussionEntry
                  children to be filled in from the protocol.
    """

    INFORMATION = "INFORMATION"
    BESCHLUSS = "BESCHLUSS"
    DISKUSSION = "DISKUSSION"


class AgendaItemVoteResult(enum.StrEnum):
    """Outcome of a BESCHLUSS-type item, transcribed by the Verwalter.

    Only meaningful for type=BESCHLUSS; INFORMATION + DISKUSSION rows
    leave this NULL. Below the quorum threshold we'd record ABGELEHNT
    regardless of yes/no split — same convention the Umlaufbeschluss
    code uses.
    """

    ANGENOMMEN = "ANGENOMMEN"
    ABGELEHNT = "ABGELEHNT"


class EtvAssembly(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "etv_assemblies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7_pk,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    status: Mapped[AssemblyStatus] = mapped_column(
        Enum(AssemblyStatus, name="assembly_status"),
        nullable=False,
        default=AssemblyStatus.GEPLANT,
        server_default=AssemblyStatus.GEPLANT.value,
    )

    # When the assembly is *planned* to start / end. Always set on create.
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    # Filled when the Verwalter marks the assembly as ABGEHALTEN.
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    actual_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    location: Mapped[str] = mapped_column(Text, nullable=False)

    # Verwalter-uploaded PDFs. agenda is the Einladung-Anhang
    # ("Tagesordnung als PDF"); protocol is the *signed* minutes that
    # confirm what happened. Storage path semantics match the existing
    # circular_resolutions.pdf_url field — Hetzner Object Storage once
    # §1.4d iter 2 lands; for v1 a local /uploads path is acceptable.
    agenda_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        # Property-scoped queue: "next ETV on this property" + "past ETVs
        # newest first." Both queries hit this index.
        Index(
            "ix_etv_assemblies_property_status_start",
            "property_id", "status", "scheduled_start",
        ),
        # Admin cross-property queue: "all upcoming ETVs across the org."
        Index(
            "ix_etv_assemblies_org_status_start",
            "organization_id", "status", "scheduled_start",
        ),
    )


class EtvAgendaItem(TimestampMixin, Base):
    """A single Tagesordnungspunkt under an EtvAssembly.

    Ordering: `(assembly_id, position)` UNIQUE. Re-ordering on the
    admin side bumps every affected position in one transaction.
    """

    __tablename__ = "etv_agenda_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7_pk,
    )
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[AgendaItemType] = mapped_column(
        Enum(AgendaItemType, name="agenda_item_type"), nullable=False,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )

    # Resolution text for BESCHLUSS items. NULL for INFORMATION /
    # DISKUSSION rows. Stored separately from `body` so the protocol
    # PDF renderer can typeset the resolution wording verbatim.
    beschluss_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vote tally — transcribed by the Verwalter from the signed
    # protocol. Defaults to zeros; only filled for BESCHLUSS rows.
    vote_yes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    vote_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    vote_abstain: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    # NULL = no quorum threshold; else result is automatically
    # ABGELEHNT if (yes + no + abstain) < required.
    vote_required_quorum: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    vote_result: Mapped[AgendaItemVoteResult | None] = mapped_column(
        Enum(AgendaItemVoteResult, name="agenda_item_vote_result"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "assembly_id", "position",
            name="uq_etv_agenda_items_assembly_position",
        ),
    )


class EtvDiscussionEntry(Base):
    """A single discussion contribution under one agenda item.

    Speaker is free-text — attendees frequently don't have portal
    accounts (proxies, Mieter, guest experts), so we don't FK to
    users/contacts.
    """

    __tablename__ = "etv_discussion_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7_pk,
    )
    agenda_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_agenda_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "agenda_item_id", "position",
            name="uq_etv_discussion_entries_agenda_item_position",
        ),
    )
