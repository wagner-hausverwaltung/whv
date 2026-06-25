import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, uuid7_pk


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    name: Mapped[str] = mapped_column(nullable=False)
    # anfragen@ auto-offer (ADR-0019): when True, inbound inquiries this org can
    # build a valid offer from are emailed automatically without manual review.
    # The "Auto-Modus" toggle on Admin -> Anfragen writes this column.
    offer_auto_send_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default="false", default=False
    )
