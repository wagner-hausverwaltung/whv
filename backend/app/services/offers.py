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

_TRANSLIT = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
}


def _safe_slug(text: str) -> str:
    """ASCII-only slug for the download filename. The Content-Disposition
    header is latin-1/ASCII, so umlauts (ß/ä/ö/ü — common in German
    addresses) must be transliterated, not just kept (they're isalnum())."""
    for src, dst in _TRANSLIT.items():
        text = text.replace(src, dst)
    keep = [c if (c.isascii() and c.isalnum()) else "-" for c in text]
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
        end_date_override=req.end_date,
        monthly_fee_net_override=req.monthly_fee_net_override,
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


# Offer cover letter (Dirk Ullrich). Generic version — the recipient/object
# specifics are intentionally left out so it fits any inquiry; the filled
# Angebot PDF is attached separately.
_OFFER_BULLETS = [
    "Umfangreiche Betreuung, die über das normale Maß (Eigentümerversammlung, "
    "Jahresabrechnung, Wirtschaftsplan) hinaus geht.",
    "Digitalisierung Ihrer Unterlagen, auch der Archivunterlagen der letzten 11 "
    "Jahre, ist inklusive.",
    "Wir sind in der Regel von 7:00 bis 18:00 Uhr telefonisch und online erreichbar.",
    "Wir steuern die Vorgänge rund um Ihr Objekt aktiv und setzen Ihre "
    "Entscheidungen konsequent und in Ihrem Interesse um.",
    "Wir managen akute Reparaturarbeiten und langfristige Sanierungen.",
    "Gern greifen wir auf Ihren bewährten Handwerkerpool zurück, bieten Ihnen "
    "aber auch einen ausgezeichneten Pool, mit dem wir arbeiten.",
    "Grundsätzlich arbeiten wir sehr eng mit den Beiräten der WEG zusammen. "
    "Jedwede finanzielle Entscheidung wird mindestens (abhängig vom Umfang) mit "
    "den Beiräten abgestimmt und ohne deren Genehmigung nicht gestartet.",
    "Wir arbeiten effektiv mit Kommunikation zwischen Ihnen und uns telefonisch, "
    "online (eMail und CASAVI Kundensystem) und bei Bedarf natürlich auch per Post.",
    "Mindestens eine Eigentümerversammlung - je nach Ihrem Bedarf persönlich oder "
    "auch online - führen wir jährlich im ersten Halbjahr durch.",
    "Grundsätzlich haben wir einen höheren Fixbetrag pro Monat, dafür belasten wir "
    "jedoch keine Sonderleistungen (wie z. B. eine zweite Eigentümerversammlung im "
    "Jahr oder dergleichen). Und wenn doch notwendig (extrem umfangreiche Sanierung) "
    "nur in Abstimmung vorab mit dem Beirat.",
    "Gern stellen wir uns Ihnen auch persönlich vor. Bitte vereinbaren Sie einen Termin mit uns.",
]

_OFFER_SIGNATURE_LINES = [
    "Dirk Ullrich",
    "Wagner Hausverwaltung GmbH",
    "",
    "Mobile +49 15679 062409",
    "Web www.wagner-hausverwaltung.com",
    "E-Mail ullrich@wagner-hausverwaltung.com",
    "",
    "Staufeneckstraße 17, 70469 Stuttgart",
]

_OFFER_EMAIL_HTML = (
    "<p>Sehr geehrte Damen und Herren,</p>"
    "<p>hiermit bewerben wir uns um die Verwaltung Ihres Objektes.</p>"
    "<p>Anbei erhalten Sie das Angebot zur Verwaltung Ihres Objektes. Da in einem "
    "VDIV-Standardangebot die individuellen Themen eher nicht berücksichtigt werden, "
    "hier noch einige Ergänzungen, die uns besser charakterisieren.</p>"
    "<p>Wir sind eine Hausverwaltung, die sich auf die Bedürfnisse kleinerer "
    "Eigentümergemeinschaften und Objekte (bis 20 WE) spezialisiert hat.</p>"
    "<p>Wir bieten Ihnen unter anderem:</p>"
    "<ul>" + "".join(f"<li>{b}</li>" for b in _OFFER_BULLETS) + "</ul>"
    "<p>Um Ihr Objekt kennenzulernen und mich Ihnen vorzustellen, würde ich mit "
    "Ihnen gern einen Termin vereinbaren. Wann würde es Ihnen passen?</p>"
    "<p>Bei Fragen bitte gern an mich wenden.</p>"
    "<p>Einen schönen Tag und freundliche Grüße!</p>"
    "<p>" + "<br>".join(_OFFER_SIGNATURE_LINES) + "</p>"
)
_OFFER_EMAIL_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "hiermit bewerben wir uns um die Verwaltung Ihres Objektes.\n\n"
    "Anbei erhalten Sie das Angebot zur Verwaltung Ihres Objektes. Da in einem "
    "VDIV-Standardangebot die individuellen Themen eher nicht berücksichtigt "
    "werden, hier noch einige Ergänzungen, die uns besser charakterisieren.\n\n"
    "Wir sind eine Hausverwaltung, die sich auf die Bedürfnisse kleinerer "
    "Eigentümergemeinschaften und Objekte (bis 20 WE) spezialisiert hat.\n\n"
    "Wir bieten Ihnen unter anderem:\n"
    + "".join(f"- {b}\n" for b in _OFFER_BULLETS)
    + "\nUm Ihr Objekt kennenzulernen und mich Ihnen vorzustellen, würde ich mit "
    "Ihnen gern einen Termin vereinbaren. Wann würde es Ihnen passen?\n\n"
    "Bei Fragen bitte gern an mich wenden.\n\n"
    "Einen schönen Tag und freundliche Grüße!\n\n" + "\n".join(_OFFER_SIGNATURE_LINES)
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
    # Persist the exact request so the offer can be re-downloaded byte-for-byte
    # later (the PDF itself isn't stored — it's regenerated from this).
    inquiry.sent_request_json = req.model_dump_json()  # type: ignore[attr-defined]
    return msg_id


# Friendly follow-up reminder (no attachment) — sent after an offer when the
# prospect hasn't replied. Deliberately short + warm; the original offer PDF is
# NOT re-attached (they already have it).
_REMINDER_EMAIL_HTML = (
    "<p>Sehr geehrte Damen und Herren,</p>"
    "<p>vor Kurzem haben wir Ihnen unser Angebot zur Verwaltung Ihres Objektes "
    "zukommen lassen. Wir wollten kurz nachfragen, ob Sie unsere Unterlagen "
    "erhalten haben und ob bereits Fragen aufgekommen sind.</p>"
    "<p>Gern stellen wir uns Ihnen auch persönlich vor und besprechen alle "
    "Details in einem unverbindlichen Termin. Wann würde es Ihnen passen?</p>"
    "<p>Wir freuen uns auf Ihre Rückmeldung.</p>"
    "<p>Einen schönen Tag und freundliche Grüße!</p>"
    "<p>" + "<br>".join(_OFFER_SIGNATURE_LINES) + "</p>"
)
_REMINDER_EMAIL_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "vor Kurzem haben wir Ihnen unser Angebot zur Verwaltung Ihres Objektes "
    "zukommen lassen. Wir wollten kurz nachfragen, ob Sie unsere Unterlagen "
    "erhalten haben und ob bereits Fragen aufgekommen sind.\n\n"
    "Gern stellen wir uns Ihnen auch persönlich vor und besprechen alle Details "
    "in einem unverbindlichen Termin. Wann würde es Ihnen passen?\n\n"
    "Wir freuen uns auf Ihre Rückmeldung.\n\n"
    "Einen schönen Tag und freundliche Grüße!\n\n" + "\n".join(_OFFER_SIGNATURE_LINES)
)


async def send_reminder_for_inquiry(
    inquiry: object,
    *,
    email_client: object,
    settings: object,
) -> str:
    """Email a friendly follow-up reminder to the inquiry's sender FROM anfragen@.

    Unlike :func:`email_offer_for_inquiry` this sends NO attachment and does NOT
    touch ``status`` / ``sent_at`` / ``generated_offer_filename`` — the original
    send must stay intact. Stamps ``last_reminder_at`` + bumps ``reminder_count``
    on success. Returns the Resend message id; raises on send failure (the caller
    must NOT flip the inquiry to FAILED — a failed reminder is not a failed offer).
    """
    from datetime import UTC, datetime

    msg_id: str = await email_client.send(  # type: ignore[attr-defined]
        to=inquiry.sender_email,  # type: ignore[attr-defined]
        subject="Ihr Angebot der Wagner Hausverwaltung — kurze Nachfrage",
        html=_REMINDER_EMAIL_HTML,
        text=_REMINDER_EMAIL_TEXT,
        from_address=settings.offer_from_address,  # type: ignore[attr-defined]
        from_name=settings.offer_from_name,  # type: ignore[attr-defined]
        reply_to=settings.offer_from_address,  # type: ignore[attr-defined]
    )
    inquiry.last_reminder_at = datetime.now(UTC)  # type: ignore[attr-defined]
    inquiry.reminder_count = (inquiry.reminder_count or 0) + 1  # type: ignore[attr-defined]
    return msg_id
