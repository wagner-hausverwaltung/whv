"""Ticket notification e-mails + the thread tag that routes replies back.

The subject carries a short tag ``[#a1b2c3]`` — the LAST six hex chars of the
ticket UUID. UUIDv7 front-loads a timestamp, so a prefix would be nearly the
same for every ticket of the day; the tail is random. Six chars keep the
inbox preview readable (owner feedback 2026-08-23); the full UUID travels in
the body footer ("Ticket-ID: …") so a quoted reply still resolves even if the
short tag were ever ambiguous. Inbound parsing: app/integrations/email/inbound.py.
"""

from __future__ import annotations

import re
import uuid

_TAG_RE = re.compile(r"\s*\[#[0-9a-fA-F]{6,32}\]\s*")


def ticket_tag(ticket_id: uuid.UUID | str) -> str:
    """``[#…]`` payload for a ticket: last 6 hex chars of its UUID, lowercase."""
    return uuid.UUID(str(ticket_id)).hex[-6:]


def strip_ticket_tags(subject: str) -> str:
    """Remove any ``[#hex]`` thread tags (6-char current, 16-char legacy) so a
    re-sent subject carries exactly one, current tag."""
    return _TAG_RE.sub(" ", subject or "").strip()


def _footer(ticket_id: str | None) -> tuple[str, str]:
    if not ticket_id:
        return "", ""
    text = f"Ticket-ID: {ticket_id}\n"
    html = f'<p style="color: #9a9a9a; font-size: 11px;">Ticket-ID: {ticket_id}</p>'
    return text, html


def render_ticket_notification_email(
    *,
    ticket_short_id: str,
    ticket_subject: str,
    sender_email: str,
    message_body: str,
    is_new_ticket: bool = False,
    ticket_id: str | None = None,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for a ticket notification email.

    `is_new_ticket=True` is the "Verwalter, an Eigentümer/Mieter just
    opened a fresh ticket" path; the subject + headline get a "Neues
    Ticket" prefix and the body greeting changes so the alert is
    unambiguous in a busy inbox. Default False keeps the existing
    "Neue Nachricht zu Ticket #…" framing for replies on existing
    threads.

    German primary. Body is plain text from the user — escaped server-side in
    the HTML version so a tag or & doesn't break the email.
    """
    # [#<short_id>] bracketed format MUST match the inbound parser's regex in
    # app/integrations/email/inbound.py — that's how reply emails route back
    # to this ticket via the support@ inbox. Renaming the bracket pattern
    # without also updating the parser breaks email-thread continuity.
    subject_prefix = "Neues Ticket: " if is_new_ticket else ""
    # One current tag, whatever the stored subject carries (legacy 16-char
    # tags from older mails, or none).
    clean_subject = strip_ticket_tags(ticket_subject)
    subject = f"[#{ticket_short_id}] {subject_prefix}{clean_subject}"
    footer_text, footer_html = _footer(ticket_id)

    headline = (
        f"Neues Ticket #{ticket_short_id}"
        if is_new_ticket
        else f"Neue Nachricht zu Ticket #{ticket_short_id}"
    )
    intro_text = (
        "ein neues Ticket wurde im WHV-Portal angelegt:"
        if is_new_ticket
        else "es gibt eine neue Nachricht zu Ihrem Ticket:"
    )

    # Escape minimal HTML special characters for the rich body. Keep simple
    # — no markdown, no auto-linking; this is a transactional notification.
    body_html = (
        message_body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )

    text = f"""\
Hallo,

{intro_text}

  Ticket:   #{ticket_short_id} — {clean_subject}
  Von:      {sender_email}

  ----- Nachricht -----
{message_body}
  ---------------------

Antworten Sie einfach direkt auf diese E-Mail — Ihre Antwort wird
automatisch dem Ticket hinzugefügt. Anhänge sind ebenfalls möglich.

Falls Sie lieber im Portal antworten möchten:
https://portal.wagner-hausverwaltung.com/

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
{footer_text}"""

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px; color: #212121;">
  {headline}
</h1>
<p><strong>{clean_subject}</strong></p>
<p style="color: #4e4b66; font-size: 14px;">Von: {sender_email}</p>

<div style="background: #f4f4f4; border-left: 4px solid #1863DC; \
padding: 12px 16px; margin: 20px 0; font-size: 14px; line-height: 1.5;">
  {body_html}
</div>

<p style="background: #e8f1fd; border-left: 4px solid #1863DC; \
padding: 12px 16px; margin: 24px 0; font-size: 14px; line-height: 1.5; color: #0c3d8a;">
  <strong>Antworten Sie einfach direkt auf diese E-Mail.</strong><br>
  Ihre Antwort wird automatisch dem Ticket hinzugefügt — Anhänge inklusive.
  Ein Besuch im Portal ist nicht nötig.
</p>

<p style="margin: 24px 0;">
  <a href="https://portal.wagner-hausverwaltung.com/" \
style="display: inline-block; padding: 8px 16px; background: transparent; color: #1863DC; \
text-decoration: none; border: 1px solid #1863DC; border-radius: 6px; font-weight: 500; \
font-size: 14px;">Im Portal öffnen</a>
</p>

<hr style="border: none; border-top: 1px solid #ebebeb; margin: 32px 0 16px;">
<p style="color: #4e4b66; font-size: 12px;">Wagner Hausverwaltung GmbH</p>
{footer_html}
</body>
</html>
"""

    return subject, html, text


def render_ticket_shared_email(
    *,
    ticket_short_id: str,
    ticket_subject: str,
    property_name: str,
    ticket_id: str | None = None,
) -> tuple[str, str, str]:
    """(subject, html, text) for "ein Anliegen wurde für alle Eigentümer
    des Objekts freigegeben".

    Subject carries the same ``[#<short_id>]`` bracket as every other
    ticket mail so a plain reply routes back into the thread via the
    inbound webhook.
    """
    # Human-readable part first, thread tag last: an inbox preview then shows
    # "Freigegebenes Ticket: Problemprotokoll", not the tag. Safe because
    # inbound.extract_ticket_ref SEARCHES the subject rather than anchoring
    # at the start, so replies still route back into the thread.
    clean_subject = strip_ticket_tags(ticket_subject)
    subject = f"Freigegebenes Ticket: {clean_subject} [#{ticket_short_id}]"
    esc = clean_subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    prop_esc = property_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    footer_text, footer_html = _footer(ticket_id)
    text = (
        "Guten Tag,\n\n"
        f"für die Liegenschaft {property_name} wurde ein Ticket für alle "
        "Eigentümer sichtbar geschaltet:\n\n"
        f"  #{ticket_short_id} — {clean_subject}\n\n"
        "Sie können das Ticket im Portal oder in der App einsehen und "
        "darauf antworten — oder einfach auf diese E-Mail antworten.\n\n"
        "Freundliche Grüße\n"
        "Wagner Hausverwaltung\n" + footer_text
    )
    html = (
        "<p>Guten Tag,</p>"
        f"<p>für die Liegenschaft <strong>{prop_esc}</strong> wurde ein Ticket "
        "für alle Eigentümer sichtbar geschaltet:</p>"
        f"<p><strong>#{ticket_short_id} — {esc}</strong></p>"
        "<p>Sie können das Ticket im Portal oder in der App einsehen und "
        "darauf antworten — oder einfach auf diese E-Mail antworten.</p>"
        "<p>Freundliche Grüße<br>Wagner Hausverwaltung</p>" + footer_html
    )
    return subject, html, text
