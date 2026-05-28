import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import (
    OrganizationScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid7_pk,
)


class DocumentFolder(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Verwalter-managed folder tree for property documents.

    Scope decision (locked in 2026-05-25): every folder belongs to exactly
    one Liegenschaft — there's no org-wide tree. Eigentümer / Mieter come
    at documents through their property, and Verwalter doesn't need a
    "shared library" for v1. parent_folder_id forms the tree (NULL =
    property root); the tree is unbounded in depth (Dropbox-style).
    """

    __tablename__ = "document_folders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL on the parent so a deletion turns descendants into
        # property-root folders rather than orphaning them. We also
        # soft-delete cascades manually in the admin endpoint.
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(nullable=False)

    __table_args__ = (
        Index(
            "ix_document_folders_property_parent",
            "property_id",
            "parent_folder_id",
        ),
    )


class DocumentKind(enum.StrEnum):
    JAHRESABRECHNUNG = "JAHRESABRECHNUNG"
    WIRTSCHAFTSPLAN = "WIRTSCHAFTSPLAN"
    PROTOKOLL = "PROTOKOLL"
    VERTRAG = "VERTRAG"
    RECHNUNG = "RECHNUNG"
    UMLAUFBESCHLUSS = "UMLAUFBESCHLUSS"
    HAUSORDNUNG = "HAUSORDNUNG"
    # Signed PDF returned by DocuSeal (ADR-0012). Stored back in the
    # document tree so signed contracts/Vollmachten are auditable.
    SIGNATUR = "SIGNATUR"
    SONSTIGES = "SONSTIGES"


class DocumentVisibility(enum.StrEnum):
    PRIVATE = "PRIVATE"
    BEIRAT_ONLY = "BEIRAT_ONLY"
    OWNERS = "OWNERS"
    TENANTS = "TENANTS"
    ALL = "ALL"


class DocumentState(enum.StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


class Document(OrganizationScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    impower_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    sharepoint_id: Mapped[str | None] = mapped_column(nullable=True)

    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buildings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Verwalter-managed folder. NULL = lives directly under the property
    # root (the implicit unnamed folder). Older Impower-imported docs are
    # all NULL until a Verwalter files them.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind"),
        nullable=False,
        server_default=text("'SONSTIGES'"),
    )
    impower_source_type: Mapped[str | None] = mapped_column(nullable=True)
    mime_type: Mapped[str | None] = mapped_column(nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(DocumentVisibility, name="document_visibility"),
        nullable=False,
        server_default=text("'PRIVATE'"),
    )
    state: Mapped[DocumentState | None] = mapped_column(
        Enum(DocumentState, name="document_state"),
        nullable=True,
    )

    raw_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stamped when owners were notified that this (relevant-kind) doc is
    # available. NULL = not yet notified; the post-sync pass picks those
    # up. Baselined to now() at migration time for the existing backlog.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_documents_org_kind", "organization_id", "kind"),)
