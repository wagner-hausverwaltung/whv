def render_invite_email(email: str, code: str, role: str) -> tuple[str, str, str]:
    """Returns (subject, html, text) for an invite email.

    German primary (WHV's market); plain-text fallback below the HTML for
    clients that don't render HTML or for accessibility tools.
    """
    subject = f"Einladung zum WHV-Portal — Code {code}"

    text = f"""\
Hallo,

Sie wurden zum Portal der Wagner Hausverwaltung GmbH eingeladen.

Einladungscode:  {code}
E-Mail-Adresse:  {email}
Rolle:           {role}

Diese Einladung ist 14 Tage gültig.

Anleitung zum Einlösen folgt, sobald das Web-Portal oder die iOS-App verfügbar ist.
Bis dahin: bewahren Sie den Code auf.

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
<h1 style="font-size: 22px; margin-bottom: 16px;">Einladung zum WHV-Portal</h1>
<p>Hallo,</p>
<p>Sie wurden zum Portal der <strong>Wagner Hausverwaltung GmbH</strong> eingeladen.</p>
<div style="background: #f5f5f5; border-left: 4px solid #1a1a1a; padding: 16px; margin: 24px 0;">
  <p style="margin: 0; font-size: 13px; color: #666;">Ihr Einladungscode</p>
  <p style="margin: 8px 0 0; font-size: 26px; font-family: ui-monospace, Menlo, monospace; \
letter-spacing: 2px;">{code}</p>
</div>
<p>
  <strong>E-Mail-Adresse:</strong> {email}<br>
  <strong>Rolle:</strong> {role}<br>
  <strong>Gültigkeit:</strong> 14 Tage
</p>
<p style="color: #666; font-size: 14px;">
  Anleitung zum Einlösen folgt, sobald das Web-Portal oder die iOS-App
  verfügbar ist. Bis dahin den Code bitte aufbewahren.
</p>
<p style="color: #666; font-size: 14px;">
  Bei Fragen:
  <a href="mailto:support@wagner-hausverwaltung.com">support@wagner-hausverwaltung.com</a>
</p>
<hr style="border: none; border-top: 1px solid #eee; margin: 32px 0 16px;">
<p style="color: #999; font-size: 12px;">Wagner Hausverwaltung GmbH</p>
</body>
</html>
"""

    return subject, html, text
