"""E-signature requests sent through DocuSeal (ADR-0012).

One row per "send this PDF to one signer". Created when the Verwalter
submits the admin Signaturen form; flipped to COMPLETED by the
`form.completed` webhook, which also links the signed PDF stored back in
the WHV document tree. Signers are email-only — never WHV-portal users —
so there's no user FK for the recipient, just email + name.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import TimestampMixin, uuid7_pk


class SignatureRequestStatus(enum.StrEnum):
    PENDING = "PENDING"  # row created, DocuSeal call not yet confirmed
    SENT = "SENT"  # DocuSeal submission created + signer emailed
    COMPLETED = "COMPLETED"  # signer signed; signed PDF stored + linked
    FAILED = "FAILED"  # DocuSeal create failed


class SignatureRequest(TimestampMixin, Base):
    __tablename__ = "signature_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional filing context — which property this signing belongs to,
    # so the signed PDF can be stored under it. NULL = org-level.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SignatureRequestStatus] = mapped_column(
        Enum(SignatureRequestStatus, name="signature_request_status"),
        nullable=False,
        default=SignatureRequestStatus.PENDING,
    )
    # DocuSeal identifiers — the submission id is how the webhook finds us.
    docuseal_template_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    docuseal_submission_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    # The signed PDF, once stored back in the WHV document tree.
    signed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
