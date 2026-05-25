"""Email template for announcement (Mitteilung) publish notifications.

Single renderer — sent when the Celery beat task fans out an
announcement to its audience. Mirrors the resolution-email shape
(subject + html + text, German primary). Attachments are added by the
caller via the EmailClient's `attachments` argument; this module only
builds the body.

Recipients: per-recipient send (one Resend call per email). BCC-style
fan-out would leak addresses across owners on the same property, and
per-recipient sends give Resend a clean bounce-tracking surface — we
trade a little extra HTTP volume for the auditability.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"
_BERLIN = ZoneInfo("Europe/Berlin")


def _fmt_berlin(dt: datetime) -> str:
    """Format a tz-aware datetime as 'DD.MM.YYYY um HH:MM Uhr' in Europe/Berlin."""
    local = dt.astimezone(_BERLIN)
    return local.strftime("%d.%m.%Y um %H:%M Uhr")


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def render_publish_email(
    *,
    announcement_id: str,
    title: str,
    body: str,
    property_name: str,
    published_at: datetime,
    attachment_count: int,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for an announcement publish notification.

    `attachment_count` is rendered as a hint line ("Anhang: 2 Dateien")
    even though the binaries are also attached to the email — some mail
    clients (Outlook on Win) hide the paperclip until the user clicks
    the message, and the hint stops them wondering whether the
    Mitteilung had something attached or not.
    """
    when = _fmt_berlin(published_at)
    link = f"{_PORTAL_BASE}/announcements/{announcement_id}"
    subject = f"Mitteilung: {title}"

    attachment_hint = ""
    if attachment_count == 1:
        attachment_hint = "  Anhang:       1 Datei (siehe E-Mail-Anhang)\n"
    elif attachment_count > 1:
        attachment_hint = f"  Anhänge:      {attachment_count} Dateien (siehe E-Mail-Anhänge)\n"

    text = f"""\
Hallo,

Ihre Hausverwaltung hat Ihnen eine neue Mitteilung gesendet:

  Betreff:      {title}
  Liegenschaft: {property_name}
  Veröffentlicht: {when}
{attachment_hint}
  ----- Inhalt -----
{body}
  ------------------

Sie können die Mitteilung im WHV-Portal einsehen und kommentieren:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    title_html = _escape_html(title)
    property_html = _escape_html(property_name)
    body_html = _escape_html(body) if body else "<em>(kein weiterer Text)</em>"

    attachment_html = ""
    if attachment_count == 1:
        attachment_html = (
            "<p style='color:#4e4b66;font-size:13px;'>📎 Diese E-Mail enthält 1 Anhang.</p>"
        )
    elif attachment_count > 1:
        attachment_html = (
            "<p style='color:#4e4b66;font-size:13px;'>"
            f"📎 Diese E-Mail enthält {attachment_count} Anhänge."
            "</p>"
        )

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px;">Neue Mitteilung</h1>
<p><strong>{title_html}</strong></p>
<p style="color: #4e4b66; font-size: 14px;">
  Liegenschaft: {property_html}<br>
  Veröffentlicht: {when}
</p>

<div style="background: #f4f4f4; border-left: 4px solid #1863DC; \
padding: 12px 16px; margin: 20px 0; font-size: 14px; line-height: 1.5;">
  {body_html}
</div>
{attachment_html}
<p style="margin: 24px 0;">
  <a href="{link}" \
style="display: inline-block; padding: 10px 20px; background: #1863DC; color: #fff; \
text-decoration: none; border-radius: 6px; font-weight: 600;">Im Portal ansehen</a>
</p>

<p style="color: #4e4b66; font-size: 13px;">
  Bei Fragen:
  <a href="mailto:support@wagner-hausverwaltung.com">support@wagner-hausverwaltung.com</a>
</p>
<hr style="border: none; border-top: 1px solid #ebebeb; margin: 32px 0 16px;">
<p style="color: #4e4b66; font-size: 12px;">Wagner Hausverwaltung GmbH</p>
</body>
</html>
"""

    return subject, html, text


def render_comment_notification_email(
    *,
    announcement_id: str,
    announcement_title: str,
    property_name: str,
    commenter_label: str,
    comment_body: str,
    commented_at: datetime,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for the "new comment on
    Mitteilung X" notification.

    Sent to the Verwalter team + everyone who has previously commented
    on the same announcement (excl. the new commenter). The portal
    link drops the recipient on the comment thread; no edit access is
    granted by visiting the link.
    """
    when = _fmt_berlin(commented_at)
    link = f"{_PORTAL_BASE}/announcements/{announcement_id}"
    subject = f"Neuer Kommentar: {announcement_title}"

    text = f"""\
Hallo,

zu folgender Mitteilung ist ein neuer Kommentar eingegangen:

  Betreff:      {announcement_title}
  Liegenschaft: {property_name}
  Verfasser:    {commenter_label}
  Eingegangen:  {when}

  ----- Kommentar -----
{comment_body}
  ---------------------

Im WHV-Portal antworten:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    title_html = _escape_html(announcement_title)
    property_html = _escape_html(property_name)
    commenter_html = _escape_html(commenter_label)
    body_html = _escape_html(comment_body)

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px;">Neuer Kommentar</h1>
<p>zu Mitteilung <strong>{title_html}</strong></p>
<p style="color: #4e4b66; font-size: 14px;">
  Liegenschaft: {property_html}<br>
  Verfasser: {commenter_html}<br>
  Eingegangen: {when}
</p>

<div style="background: #f4f4f4; border-left: 4px solid #1863DC; \
padding: 12px 16px; margin: 20px 0; font-size: 14px; line-height: 1.5;">
  {body_html}
</div>

<p style="margin: 24px 0;">
  <a href="{link}" \
style="display: inline-block; padding: 10px 20px; background: #1863DC; color: #fff; \
text-decoration: none; border-radius: 6px; font-weight: 600;">Im Portal antworten</a>
</p>

<p style="color: #4e4b66; font-size: 13px;">
  Bei Fragen:
  <a href="mailto:support@wagner-hausverwaltung.com">support@wagner-hausverwaltung.com</a>
</p>
<hr style="border: none; border-top: 1px solid #ebebeb; margin: 32px 0 16px;">
<p style="color: #4e4b66; font-size: 12px;">Wagner Hausverwaltung GmbH</p>
</body>
</html>
"""

    return subject, html, text
