"""Registered push-notification devices.

One row per (user, APNs device token). The iOS app registers its
token on sign-in via `POST /me/devices` and unregisters on sign-out
via `DELETE /me/devices/{token}`. The push fan-out service
(`app/services/push.py`) looks devices up by user_id when an event
that warrants a push fires (ETV comment, ticket message, new
ticket) — the same recipient set the email notifications use.

Token lifecycle:
* Tokens rotate — iOS can hand the app a fresh token any launch.
  We upsert on `apns_token` so a re-register just bumps
  `last_seen_at` rather than duplicating.
* APNs replies 410 Unregistered when a token is dead (app deleted,
  notifications revoked). The push service soft-deletes those so
  we stop trying.
* `environment` ('sandbox' | 'production') is stamped at register
  time because a token is only valid against the APNs host that
  minted it — a TestFlight token won't work on the sandbox
  gateway and vice versa. The push service filters by the host it's
  configured for.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import SoftDeleteMixin, uuid7_pk


class DevicePlatform(enum.StrEnum):
    IOS = "IOS"


class DeviceEnvironment(enum.StrEnum):
    SANDBOX = "SANDBOX"
    PRODUCTION = "PRODUCTION"


class UserDevice(SoftDeleteMixin, Base):
    __tablename__ = "user_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The APNs device token (hex string). Unique so re-registration
    # upserts instead of duplicating.
    apns_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(DevicePlatform, name="device_platform"),
        nullable=False,
        default=DevicePlatform.IOS,
    )
    # Which APNs host minted this token. The push service only sends
    # to tokens matching the host it's configured for.
    environment: Mapped[DeviceEnvironment] = mapped_column(
        Enum(DeviceEnvironment, name="device_environment"),
        nullable=False,
        default=DeviceEnvironment.PRODUCTION,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
