"""Email templates for Eigentümerversammlung (ETV) — currently just
the new-comment notification.

Mirrors the announcement-comment notification shape. Sent on every
new comment to (a) every active Verwalter in the org and (b) any
prior commenter on the same thread, minus the new author.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"
_BERLIN = ZoneInfo("Europe/Berlin")


def _fmt_berlin(dt: datetime) -> str:
    return dt.astimezone(_BERLIN).strftime("%d.%m.%Y um %H:%M Uhr")


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def render_assembly_comment_notification_email(
    *,
    assembly_id: str,
    assembly_title: str,
    property_name: str,
    commenter_label: str,
    comment_body: str,
    commented_at: datetime,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for the "new comment on
    Versammlung X" notification. Without this email the Verwalter
    would have to actively poll each assembly for new questions —
    which they don't.

    The portal link drops the recipient on the assembly detail page
    where the comments section is rendered.
    """
    when = _fmt_berlin(commented_at)
    link = f"{_PORTAL_BASE}/assemblies/{assembly_id}"
    subject = f"Neue Frage zur Versammlung: {assembly_title}"

    text = f"""\
Hallo,

zur folgenden Eigentümerversammlung ist ein neuer Kommentar
eingegangen:

  Betreff:      {assembly_title}
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

    title_html = _escape_html(assembly_title)
    property_html = _escape_html(property_name)
    commenter_html = _escape_html(commenter_label)
    body_html = _escape_html(comment_body)

    # Inline styles on a single line where the HTML demands it —

    # rendering (some don't tolerate whitespace between attrs).
    _body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "sans-serif; color: #1d1d1f; max-width: 640px; "
        "margin: 0 auto; padding: 24px;"
    )
    _label_style = "padding: 4px 12px 4px 0; color: #6e6e73;"
    _quote_style = (
        "border-left: 3px solid #0066cc; padding: 8px 12px; "
        "background: #f5f5f7; margin: 0 0 16px; font-size: 14px;"
    )
    _cta_style = (
        "display: inline-block; padding: 10px 16px; "
        "background: #0066cc; color: #fff; "
        "text-decoration: none; border-radius: 6px;"
    )
    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="{_body_style}">
  <h2 style="margin: 0 0 16px; font-size: 18px;">Neue Frage zur Versammlung</h2>
  <p style="margin: 0 0 16px;">
    Zur Eigentümerversammlung <strong>{title_html}</strong>
    ({property_html}) ist ein neuer Kommentar eingegangen.
  </p>
  <table style="border-collapse: collapse; margin: 0 0 16px; font-size: 14px;">
    <tr><td style="{_label_style}">Verfasser:</td><td>{commenter_html}</td></tr>
    <tr><td style="{_label_style}">Eingegangen:</td><td>{when}</td></tr>
  </table>
  <div style="{_quote_style}">
    {body_html}
  </div>
  <p style="margin: 0 0 24px;">
    <a href="{link}" style="{_cta_style}">Im Portal öffnen + antworten</a>
  </p>
  <p style="margin: 0; font-size: 12px; color: #6e6e73;">
    Wagner Hausverwaltung GmbH · support@wagner-hausverwaltung.com
  </p>
</body>
</html>
"""

    return subject, html, text
