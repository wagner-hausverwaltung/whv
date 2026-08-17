def render_ticket_notification_email(
    *,
    ticket_short_id: str,
    ticket_subject: str,
    sender_email: str,
    message_body: str,
    is_new_ticket: bool = False,
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
    if f"[#{ticket_short_id}]" not in ticket_subject:
        subject = f"[#{ticket_short_id}] {subject_prefix}{ticket_subject}"
    else:
        subject = f"{subject_prefix}{ticket_subject}" if subject_prefix else ticket_subject

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

  Ticket:   #{ticket_short_id} — {ticket_subject}
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
"""

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px; color: #212121;">
  {headline}
</h1>
<p><strong>{ticket_subject}</strong></p>
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
</body>
</html>
"""

    return subject, html, text


def render_ticket_shared_email(
    *,
    ticket_short_id: str,
    ticket_subject: str,
    property_name: str,
) -> tuple[str, str, str]:
    """(subject, html, text) for "ein Anliegen wurde für alle Eigentümer
    des Objekts freigegeben".

    Subject carries the same ``[#<short_id>]`` bracket as every other
    ticket mail so a plain reply routes back into the thread via the
    inbound webhook.
    """
    # Human-readable part first, thread tag last: an inbox preview then shows
    # "Freigegebenes Ticket: Problemprotokoll", not 16 hex chars. Safe because
    # inbound.extract_ticket_ref SEARCHES the subject rather than anchoring
    # at the start, so replies still route back into the thread.
    subject = f"Freigegebenes Ticket: {ticket_subject} [#{ticket_short_id}]"
    esc = ticket_subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    prop_esc = property_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = (
        "Guten Tag,\n\n"
        f"für die Liegenschaft {property_name} wurde ein Ticket für alle "
        "Eigentümer sichtbar geschaltet:\n\n"
        f"  #{ticket_short_id} — {ticket_subject}\n\n"
        "Sie können das Ticket im Portal oder in der App einsehen und "
        "darauf antworten — oder einfach auf diese E-Mail antworten.\n\n"
        "Freundliche Grüße\n"
        "Wagner Hausverwaltung"
    )
    html = (
        "<p>Guten Tag,</p>"
        f"<p>für die Liegenschaft <strong>{prop_esc}</strong> wurde ein Ticket "
        "für alle Eigentümer sichtbar geschaltet:</p>"
        f"<p><strong>#{ticket_short_id} — {esc}</strong></p>"
        "<p>Sie können das Ticket im Portal oder in der App einsehen und "
        "darauf antworten — oder einfach auf diese E-Mail antworten.</p>"
        "<p>Freundliche Grüße<br>Wagner Hausverwaltung</p>"
    )
    return subject, html, text
