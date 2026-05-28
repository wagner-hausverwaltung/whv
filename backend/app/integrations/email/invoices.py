"""Email template for the "Rechnung gebucht" owner notification.

Fires from the Impower invoices webhook when an invoice reaches state
BOOKED, to the owners (Eigentümer + Beirat) of the Liegenschaft.
"""

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def render_booked_invoice_notification_email(
    *,
    property_name: str,
    vendor_name: str,
    amount_label: str,
    invoice_number: str | None,
) -> tuple[str, str, str]:
    """Returns (subject, html, text). Links to the property's
    Dienstleister/invoice view in the portal."""
    link = f"{_PORTAL_BASE}/"
    subject = f"Neue Rechnung gebucht: {vendor_name} ({property_name})"
    number_line = f"\n  Beleg:        {invoice_number}" if invoice_number else ""

    text = f"""\
Hallo,

für Ihre Liegenschaft wurde eine Rechnung gebucht:

  Liegenschaft: {property_name}
  Dienstleister:{vendor_name}
  Betrag:       {amount_label}{number_line}

Details im WHV-Portal:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    property_html = _escape_html(property_name)
    vendor_html = _escape_html(vendor_name)
    amount_html = _escape_html(amount_label)
    number_html = _escape_html(invoice_number) if invoice_number else None

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
    number_row = (
        f'<tr><td style="{_label_style}">Beleg:</td><td>{number_html}</td></tr>'
        if number_html
        else ""
    )
    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="{_body_style}">
  <h2 style="margin: 0 0 16px; font-size: 18px;">Neue Rechnung gebucht</h2>
  <p style="margin: 0 0 16px;">
    Für Ihre Liegenschaft <strong>{property_html}</strong> wurde eine
    Rechnung gebucht.
  </p>
  <table style="border-collapse: collapse; margin: 0 0 16px; font-size: 14px;">
    <tr><td style="{_label_style}">Dienstleister:</td><td>{vendor_html}</td></tr>
    <tr><td style="{_label_style}">Betrag:</td><td>{amount_html}</td></tr>
    {number_row}
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
