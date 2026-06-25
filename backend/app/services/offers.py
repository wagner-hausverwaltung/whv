"""Offer (Angebot) generation orchestration (ADR-0019).

Turns an :class:`OfferGenerateRequest` into a filled offer PDF by computing the
pricing and stamping the per-customer values onto the committed base template.
Side-effect-free + Celery-free so it's reusable from the manual admin endpoint
(now) and the automatic inbound pipeline (Phase 2).
"""

from __future__ import annotations

from datetime import date

from app.integrations.pdf.offer_document import (
    MvOfferInput,
    WegOfferInput,
    load_base_template,
    render_mv_offer,
    render_weg_offer,
)
from app.schemas.offer import OfferGenerateRequest
from app.services.offer_pricing import price_offer


def _safe_slug(text: str) -> str:
    keep = [c if c.isalnum() else "-" for c in text]
    return "".join(keep).strip("-")[:60] or "Angebot"


def generate_offer(req: OfferGenerateRequest, *, today: date | None = None) -> tuple[bytes, str]:
    """Render the offer PDF; return (pdf_bytes, suggested_filename)."""
    pricing = price_offer(
        req.art,
        units=req.units,
        start_date=req.start_date,
        term_years=req.term_years,
        rate_per_unit_net=req.rate_per_unit_net,
        today=today,
    )
    base = load_base_template(req.art)

    if req.art == "WEG":
        pdf = render_weg_offer(
            base,
            WegOfferInput(
                object_street=req.object_street or "",
                object_plz_city=req.object_plz_city or "",
                pricing=pricing,
            ),
        )
        label = req.object_street or "WEG"
    else:
        offer_date = req.offer_date or today or date.today()
        pdf = render_mv_offer(
            base,
            MvOfferInput(
                recipient_name=req.recipient_name or "",
                recipient_street=req.recipient_street or "",
                recipient_plz_city=req.recipient_plz_city or "",
                salutation=req.salutation or "",
                objects=req.objects or [],
                pricing=pricing,
                offer_date=offer_date,
                representative_name=req.representative_name,
                representative_street=req.representative_street,
                representative_plz_city=req.representative_plz_city,
            ),
        )
        label = req.recipient_name or "MV"

    filename = f"Angebot-{req.art}-{_safe_slug(label)}.pdf"
    return pdf, filename


_OFFER_EMAIL_HTML = (
    "<p>Guten Tag,</p><p>vielen Dank für Ihre Anfrage. Im Anhang finden Sie "
    "unser Angebot.</p><p>Mit freundlichen Grüßen<br>Wagner Hausverwaltung GmbH</p>"
)
_OFFER_EMAIL_TEXT = (
    "Guten Tag,\n\nvielen Dank für Ihre Anfrage. Im Anhang finden Sie unser "
    "Angebot.\n\nMit freundlichen Grüßen\nWagner Hausverwaltung GmbH"
)


async def email_offer_for_inquiry(
    inquiry: object,
    req: OfferGenerateRequest,
    *,
    email_client: object,
    settings: object,
    today: date | None = None,
) -> str:
    """Generate the offer PDF, email it to the inquiry's sender FROM anfragen@,
    and stamp the inquiry SENT. Returns the Resend message id; raises on send
    failure so the caller can mark the inquiry FAILED.

    Shared by the Celery auto-send task and the admin "approve & send" endpoint
    so the send path (from-address, attachment, status stamping) is identical.
    """
    import asyncio
    import base64
    from datetime import UTC, datetime

    from app.models import OfferInquiryStatus

    pdf, filename = await asyncio.to_thread(generate_offer, req, today=today)
    msg_id: str = await email_client.send(  # type: ignore[attr-defined]
        to=inquiry.sender_email,  # type: ignore[attr-defined]
        subject="Ihr Angebot der Wagner Hausverwaltung",
        html=_OFFER_EMAIL_HTML,
        text=_OFFER_EMAIL_TEXT,
        attachments=[{"filename": filename, "content": base64.b64encode(pdf).decode("ascii")}],
        from_address=settings.offer_from_address,  # type: ignore[attr-defined]
        from_name=settings.offer_from_name,  # type: ignore[attr-defined]
        reply_to=settings.offer_from_address,  # type: ignore[attr-defined]
    )
    inquiry.status = OfferInquiryStatus.SENT.value  # type: ignore[attr-defined]
    inquiry.sent_at = datetime.now(UTC)  # type: ignore[attr-defined]
    inquiry.sent_message_id = msg_id  # type: ignore[attr-defined]
    inquiry.generated_offer_filename = filename  # type: ignore[attr-defined]
    return msg_id
