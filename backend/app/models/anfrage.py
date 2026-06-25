"""OfferInquiry (Anfrage) — an inbound anfragen@ offer request (ADR-0019, Ph 2).

A prospect emails anfragen@wagner-hausverwaltung.com; the SES inbound webhook
records the raw inquiry here (instead of opening a ticket), then a Celery task
runs LLM extraction to fill `art` / object / units / desired_start. From there:

  - high-confidence + all required fields + the auto-send kill switch ON
    → generate the offer and email it back, status SENT;
  - otherwise → status NEEDS_REVIEW for a Verwalter to finish in the admin UI.

`status` + `art` are free-form Text (evolvable without a pg enum / migration);
the `OfferInquiryStatus` StrEnum below is the canonical set used in code.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class OfferInquiryStatus(enum.StrEnum):
    NEW = "NEW"  # received, not yet extracted
    EXTRACTED = "EXTRACTED"  # extraction done, awaiting send/review decision
    NEEDS_REVIEW = "NEEDS_REVIEW"  # low confidence / missing fields / auto-send off
    SENT = "SENT"  # offer generated + emailed back
    FAILED = "FAILED"  # extraction or send error
    IGNORED = "IGNORED"  # not an offer request / spam


class OfferInquiry(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "offer_inquiries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)

    # Raw inbound inquiry (prospect PII — kept for the business purpose of
    # answering the inquiry; see ADR-0019 DSGVO note).
    sender_email: Mapped[str] = mapped_column(Text, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # SES message id — dedupe a retried SNS delivery into one inquiry.
    received_message_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, default=OfferInquiryStatus.NEW.value)

    # Extracted fields (NULL until the LLM task runs).
    art: Mapped[str | None] = mapped_column(Text, nullable=True)  # "WEG" | "MV"
    object_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desired_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    extraction_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome.
    generated_offer_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
