"""Per-user notification preferences.

One row per (user, category). Each row carries two independent
channel switches: push (APNs) and email (Resend). The matrix is
surfaced + edited identically in the web portal and the iOS app via
`GET/PUT /me/notification-settings`, so a user's choice follows them
across devices.

Opt-out semantics (decided 2026-05-28, ADR-0011): the ABSENCE of a
row means "all on" — every category notifies on both channels by
default, matching the behaviour before this feature existed. A row is
written only when the user actually toggles something off (or back
on). So `effective(user, category, channel)` = the row's flag if a
row exists, else True. This keeps the table small and means a brand-
new user (and every existing user at rollout) loses nothing.

Categories map 1:1 onto the notification sites:
* ANNOUNCEMENT    — a new Mitteilung/News was published
* TICKET          — new Anliegen + new replies
* ETV_COMMENT     — new question/comment on an Eigentümerversammlung
* ETV_INVITATION  — a new Einladung zur Eigentümerversammlung arrived
* DOCUMENT        — a new relevant document (Jahresabrechnung,
                    Wirtschaftsplan, Protokoll, Rechnung) is available
"""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, uuid7_pk


class NotificationCategory(enum.StrEnum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    TICKET = "TICKET"
    ETV_COMMENT = "ETV_COMMENT"
    ETV_INVITATION = "ETV_INVITATION"
    DOCUMENT = "DOCUMENT"
    INVOICE = "INVOICE"


class NotificationChannel(enum.StrEnum):
    """Not persisted as a column — the two channels are separate
    boolean columns — but used by the API + filtering helpers to talk
    about a single channel."""

    PUSH = "PUSH"
    EMAIL = "EMAIL"


class UserNotificationPreference(TimestampMixin, Base):
    __tablename__ = "user_notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[NotificationCategory] = mapped_column(
        Enum(NotificationCategory, name="notification_category"),
        nullable=False,
    )
    # Default True so a freshly-inserted row (e.g. user toggled the
    # *other* channel off) still notifies on this one until explicitly
    # disabled.
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_pref_user_category"),
    )
