"""Announcements (Mitteilungen) — property-scoped messages from Verwalter
to Eigentümer / Mieter / Beirat.

Lifecycle:
  1. Verwalter creates an announcement → `scheduled_publish_at = now() + 10min`,
     `notification_sent_at = NULL`.
  2. While unpublished, every PATCH bumps `scheduled_publish_at` to
     `now() + 10min` (editorial-buffer reset). Once published, edits are
     still allowed but the timer is frozen (notification_sent_at !=
     NULL → published, mutable with `updated_at` advancing).
  3. A 1-minute Celery beat picks up rows where `scheduled_publish_at
     <= now() AND notification_sent_at IS NULL AND deleted_at IS NULL`,
     fans out one email per audience-matched recipient, and stamps
     `notification_sent_at` so the row drops out of the publish-due
     partial index.

Audience is three independent booleans. The role-filter is applied at
fan-out time and at portal list/detail time, so post-publish edits to
the flags take effect immediately on the portal view. The DB CHECK
constraint ensures at least one flag is true; the API enforces the
same at request time so the error message is clean.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class Announcement(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    # Three audience flags — see module docstring. At least one must be
    # true; enforced both at DB level (CHECK) and at request time.
    audience_eigentuemer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    audience_mieter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    audience_beirat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # The publish timer. Read by the Celery beat scan; written by the
    # service helpers (create + update + publish_now).
    scheduled_publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Filled in once the fan-out task completes. Doubles as the
    # "published?" flag for read-side filtering.
    notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_announcements_property_scheduled",
            "property_id",
            "scheduled_publish_at",
        ),
        # Mirrors the partial index declared in the migration so SA's
        # autogen diff stays empty. The actual partial-index DDL lives
        # in the migration; this is just a hint for query planners
        # consulting model metadata.
        Index(
            "ix_announcements_due_for_publish",
            "scheduled_publish_at",
            postgresql_where=("notification_sent_at IS NULL AND deleted_at IS NULL"),
        ),
    )


class AnnouncementAttachment(Base):
    """File attached to an announcement — typically a PDF protocol or a
    photo of an outage. Same storage convention as
    `ticket_message_attachments`: `storage_url` is `"local-disk:<suffix>"`,
    bytes live at `{announcement_attachment_dir}/{id}{suffix}`.
    """

    __tablename__ = "announcement_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
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


class AnnouncementComment(Base):
    """User-authored reply under a published announcement.

    Authoring requires (a) the announcement to be published
    (notification_sent_at NOT NULL) and (b) the author to be a property
    participant whose role matches one of the audience flags.

    Moderation is hide-only: `is_hidden=true` removes the row from
    non-admin views but the comment stays in the DB. `hidden_by` /
    `hidden_at` / `hidden_reason` capture who/when/why.
    """

    __tablename__ = "announcement_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("announcements.id", ondelete="CASCADE"),
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

    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    hidden_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_announcement_comments_thread",
            "announcement_id",
            "created_at",
        ),
    )
