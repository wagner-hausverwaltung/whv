"""Email template for the "new document available" notification.

Fires from the post-sync pass when a relevant new document
(Jahresabrechnung, Wirtschaftsplan, Protokoll, Umlaufbeschluss) lands
for a property, to the owners/parties who can see it.
"""

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


def render_document_notification_email(
    *,
    document_name: str,
    kind_label: str,
    property_name: str,
) -> tuple[str, str, str]:
    """Returns (subject, html, text). Links to the property's documents
    tab in the portal where the file can be downloaded."""
    link = f"{_PORTAL_BASE}/documents"
    subject = f"Neues Dokument: {kind_label} ({property_name})"

    text = f"""\
Hallo,

für Ihre Liegenschaft steht ein neues Dokument bereit:

  Liegenschaft: {property_name}
  Art:          {kind_label}
  Dokument:     {document_name}

Im WHV-Portal ansehen + herunterladen:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    name_html = _escape_html(document_name)
    kind_html = _escape_html(kind_label)
    property_html = _escape_html(property_name)

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
  <h2 style="margin: 0 0 16px; font-size: 18px;">Neues Dokument verfügbar</h2>
  <p style="margin: 0 0 16px;">
    Für Ihre Liegenschaft <strong>{property_html}</strong> steht ein
    neues Dokument bereit.
  </p>
  <table style="border-collapse: collapse; margin: 0 0 16px; font-size: 14px;">
    <tr><td style="{_label_style}">Art:</td><td>{kind_html}</td></tr>
    <tr><td style="{_label_style}">Dokument:</td><td>{name_html}</td></tr>
  </table>
  <p style="margin: 0 0 24px;">
    <a href="{link}" style="{_cta_style}">Im Portal öffnen</a>
  </p>
  <p style="margin: 0; font-size: 12px; color: #6e6e73;">
    Wagner Hausverwaltung GmbH · support@wagner-hausverwaltung.com
  </p>
</body>
</html>
"""

    return subject, html, text
