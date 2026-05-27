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
    JSON,
    BigInteger,
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

    GEPLANT = "GEPLANT"  # date scheduled, invitations not yet sent
    EINGELADEN = "EINGELADEN"  # invitations dispatched, agenda locked
    ABGEHALTEN = "ABGEHALTEN"  # assembly happened, protocol on the way / uploaded
    ABGESAGT = "ABGESAGT"  # cancelled before it took place


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


class AgendaItemVotingBasis(enum.StrEnum):
    """The three Stimmrecht modes German WEG-Recht recognises.

    KOPF   — Kopfprinzip. One vote per Eigentümer regardless of how
             many Einheiten / MEA they hold. Default for many WEG
             decisions; required by some §-rules.
    MEA    — Anteilsprinzip. Votes weighted by Miteigentumsanteile
             (typically out of 1000 or 10000). Required for
             building-affecting decisions (§ 16 WEG etc.).
    OBJEKT — Objektprinzip. One vote per Einheit / Wohnung. Some
             communities pick this in the Teilungserklärung.

    Stored on the agenda item because different TOPs in the same
    meeting can have different bases (§-rule determines).
    """

    KOPF = "KOPF"
    MEA = "MEA"
    OBJEKT = "OBJEKT"


class EtvAssembly(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "etv_assemblies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7_pk,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[AssemblyStatus] = mapped_column(
        Enum(AssemblyStatus, name="assembly_status"),
        nullable=False,
        default=AssemblyStatus.GEPLANT,
        server_default=AssemblyStatus.GEPLANT.value,
    )

    # When the assembly is *planned* to start / end. Always set on create.
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # Filled when the Verwalter marks the assembly as ABGEHALTEN.
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    actual_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    location: Mapped[str] = mapped_column(Text, nullable=False)

    # Microsoft Teams meet-up URL for hybrid ETVs. Auto-extracted from
    # the invitation PDF when present; editable by Verwalter. Surfaced
    # as a "Teams-Meeting beitreten" CTA on the portal + iOS detail
    # views so attending owners can join from any device without
    # hunting through the PDF.
    teams_meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Verwalter-uploaded PDFs.
    # `agenda_pdf_url` is retained for a potential separate "Tagesordnung
    # als Anhang" upload — in practice Verwalter ship a single combined
    # Einladung PDF and use `invitation_pdf_url`.
    # `invitation_pdf_url` is the Einladung PDF — drives the LLM
    # extraction (ADR-0008) and is served to owners as the "Einladung
    # herunterladen" affordance on the assembly detail page.
    # `protocol_pdf_url` is the *signed* minutes confirming what
    # happened. Always uploaded after the assembly.
    # Storage path semantics: relative filename under settings.{etv_invitation_dir,
    # etv_protocol_dir}; Hetzner Object Storage once §1.4d iter 2 lands.
    agenda_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    protocol_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- LLM extraction tracking (ADR-0008) ---
    # Set when the Celery extraction task last wrote into this row.
    # Distinct from `verified_at`: auto_extracted is what the model
    # thinks; verified is what a Verwalter signed off on. The admin
    # SPA renders a "KI-extrahiert · bitte prüfen" badge when
    # auto_extracted_at IS NOT NULL AND verified_at IS NULL.
    auto_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Which document we actually read to derive the extraction.
    # Lets us re-run extraction on the same source for A/B-ing prompt
    # changes, and lets the admin UI link "Quelle ansehen" → the
    # original Impower invitation PDF.
    auto_extracted_source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Raw extraction payload preserved verbatim. Cheap to keep
    # (≤ a few KB per row); enables future "what did the model see
    # before we corrected it" debugging without re-calling the API.
    auto_extracted_raw: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Post-meeting extraction tracked separately from invitation
    # extraction. The protocol is the source of truth for vote
    # tallies + final Beschlusstext + discussion — the invitation
    # only proposes; the meeting may amend.
    protocol_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    protocol_extracted_source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    protocol_extracted_raw: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    # Verwalter sign-off on the protocol extraction. Separate from
    # `verified_at` (which now means "invitation-side verified") so
    # the Verwalter can sign off on the invitation when it's uploaded
    # without blocking the later protocol extraction. Once this is
    # set, the protocol extractor skips on re-runs.
    protocol_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    protocol_verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Property-scoped queue: "next ETV on this property" + "past ETVs
        # newest first." Both queries hit this index.
        Index(
            "ix_etv_assemblies_property_status_start",
            "property_id",
            "status",
            "scheduled_start",
        ),
        # Admin cross-property queue: "all upcoming ETVs across the org."
        Index(
            "ix_etv_assemblies_org_status_start",
            "organization_id",
            "status",
            "scheduled_start",
        ),
    )


class EtvAgendaItem(TimestampMixin, Base):
    """A single Tagesordnungspunkt under an EtvAssembly.

    Ordering: `(assembly_id, position)` UNIQUE. Re-ordering on the
    admin side bumps every affected position in one transaction.
    """

    __tablename__ = "etv_agenda_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7_pk,
    )
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[AgendaItemType] = mapped_column(
        Enum(AgendaItemType, name="agenda_item_type"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    # Resolution text for BESCHLUSS items. NULL for INFORMATION /
    # DISKUSSION rows. Stored separately from `body` so the protocol
    # PDF renderer can typeset the resolution wording verbatim.
    beschluss_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vote tally — transcribed by the Verwalter from the signed
    # protocol. Defaults to zeros; only filled for BESCHLUSS rows.
    vote_yes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    vote_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    vote_abstain: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # NULL = no quorum threshold; else result is automatically
    # ABGELEHNT if (yes + no + abstain) < required.
    vote_required_quorum: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    vote_result: Mapped[AgendaItemVoteResult | None] = mapped_column(
        Enum(AgendaItemVoteResult, name="agenda_item_vote_result"),
        nullable=True,
    )
    # Stimmrecht — which voting basis the protocol used for THIS TOP.
    # Different TOPs in the same meeting can have different bases
    # depending on §-rule. NULL when not stated / not a BESCHLUSS.
    voting_basis: Mapped[AgendaItemVotingBasis | None] = mapped_column(
        Enum(AgendaItemVotingBasis, name="agenda_item_voting_basis"),
        nullable=True,
    )
    # Anwesend — votes available for THIS vote (count is interpreted
    # against `voting_basis`: per-head, MEA share, or per-Einheit).
    # Often ≠ yes+no+abstain because owners can leave the room or
    # arrive between TOPs. NULL when not stated in the protocol.
    present_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "assembly_id",
            "position",
            name="uq_etv_agenda_items_assembly_position",
        ),
    )


class EtvAssemblyComment(Base):
    """Q&A thread under an ETV. Distinct from `EtvDiscussionEntry`
    (which captures Wortmeldungen *during* the meeting) — these are
    post-publication questions from Eigentümer + replies from the
    Verwalter, visible alongside the formal protocol.

    Trimmed shape vs. `announcement_comments`: no moderation flags,
    no version history table. Body is one of two things:

      1. A question from an Eigentümer.
      2. A reply from the Verwalter / Beirat.

    Identity comes from `author_user_id`; the rendering layer uses
    the user's role to badge it visually.
    """

    __tablename__ = "etv_assembly_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7_pk,
    )
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # NULL = never edited. Renderer shows "(bearbeitet)" when set.
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class EtvDiscussionEntry(Base):
    """A single discussion contribution under one agenda item.

    Speaker is free-text — attendees frequently don't have portal
    accounts (proxies, Mieter, guest experts), so we don't FK to
    users/contacts.
    """

    __tablename__ = "etv_discussion_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7_pk,
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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "agenda_item_id",
            "position",
            name="uq_etv_discussion_entries_agenda_item_position",
        ),
    )


class EtvAgendaItemAttachment(Base):
    """PDF / document attached to a single Tagesordnungspunkt.

    The user-visible feature: attendees see supporting docs inline
    with the item ("hier ist der Angebotsvergleich für TOP 3") rather
    than at the end of the meeting where the protocol PDF lands. The
    Verwalter uploads from the admin SPA's per-item editor; everyone
    on the property can download + preview.

    Mirrors `announcement_attachments` / `ticket_message_attachments`
    storage convention: `storage_url` = `"local-disk:<suffix>"`, bytes
    live at `{etv_attachment_dir}/{id}{suffix}`. Same Hetzner Object
    Storage migration plan (REQUIREMENTS.md §1.4d iter 2) applies.

    Org scope rides along via the agenda item → assembly →
    organization_id chain; storing it on this thin row would just be
    denormalised duplication.
    """

    __tablename__ = "etv_agenda_item_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    agenda_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_agenda_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # See class docstring for the "local-disk:<suffix>" convention.
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
