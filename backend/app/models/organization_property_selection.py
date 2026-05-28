"""Org-wide saved property selection for the admin units/fee summary.

One row per organization (shared across all Verwalter): whichever
Verwalter changes the checkbox set on the admin properties table, every
colleague sees the same selection + derived management fee. We persist
only the property ids — the fee is recomputed client-side from the
hardcoded step function, so the schedule lives in exactly one place.
"""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, uuid7_pk


class OrganizationPropertySelection(TimestampMixin, Base):
    __tablename__ = "organization_property_selections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # The checked property ids, stored as a JSON array of UUID strings.
    property_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Who last changed the shared selection (audit nicety; nullable so a
    # deleted user doesn't block the row).
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
