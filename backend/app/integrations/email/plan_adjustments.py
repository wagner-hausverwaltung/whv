"""Email template for the "Hausgeld-Anpassung" owner notification.

Fires from the nightly plan-adjustment poll when the Verwalter has
marked a suggestion as INFORMED, to the owner(s) on that contract.
"""

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def render_plan_adjustment_notification_email(
    *,
    property_name: str,
    previous_label: str,
    new_label: str,
    effective_date: str,
) -> tuple[str, str, str]:
    """Returns (subject, html, text). Amounts are pre-formatted strings
    (e.g. '250,00 €'); effective_date is a display string (DD.MM.YYYY)."""
    link = f"{_PORTAL_BASE}/"
    subject = f"Anpassung Ihres Hausgeldes ({property_name})"

    text = f"""\
Hallo,

das Hausgeld für Ihre Liegenschaft wird angepasst:

  Liegenschaft: {property_name}
  Bisher:       {previous_label}
  Neu:          {new_label}
  Gültig ab:    {effective_date}

Details + Hintergrund finden Sie im WHV-Portal:
{link}

Bei Fragen wenden Sie sich an die Verwaltung:
support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    property_html = _escape_html(property_name)
    previous_html = _escape_html(previous_label)
    new_html = _escape_html(new_label)
    date_html = _escape_html(effective_date)

    _body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "sans-serif; color: #1d1d1f; max-width: 640px; "
        "margin: 0 auto; padding: 24px;"
    )
    _label_style = "padding: 4px 12px 4px 0; color: #6e6e73;"
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
  <h2 style="margin: 0 0 16px; font-size: 18px;">Anpassung Ihres Hausgeldes</h2>
  <p style="margin: 0 0 16px;">
    Das Hausgeld für Ihre Liegenschaft <strong>{property_html}</strong>
    wird angepasst.
  </p>
  <table style="border-collapse: collapse; margin: 0 0 16px; font-size: 14px;">
    <tr><td style="{_label_style}">Bisher:</td><td>{previous_html}</td></tr>
    <tr><td style="{_label_style}">Neu:</td><td><strong>{new_html}</strong></td></tr>
    <tr><td style="{_label_style}">Gültig ab:</td><td>{date_html}</td></tr>
  </table>
  <p style="margin: 0 0 24px;">
    <a href="{link}" style="{_cta_style}">Im Portal ansehen</a>
  </p>
  <p style="margin: 0; font-size: 12px; color: #6e6e73;">
    Wagner Hausverwaltung GmbH · support@wagner-hausverwaltung.com
  </p>
</body>
</html>
"""

    return subject, html, text
