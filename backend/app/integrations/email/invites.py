from urllib.parse import quote

_PORTAL_BASE = "https://portal.wagner-hausverwaltung.com"


def render_invite_email(email: str, code: str, role: str) -> tuple[str, str, str]:
    """Returns (subject, html, text) for an invite email.

    German primary (WHV's market); plain-text fallback below the HTML for
    clients that don't render HTML or for accessibility tools.

    The CTA links to the portal's invite-redeem page with the code
    pre-filled (`/invite?code=…`); the code box stays as a manual
    fallback. Same redeem page for every role — owners stay in the
    portal, a Verwalter continues to the admin area after setting their
    password.
    """
    subject = f"Einladung zum WHV-Portal — Code {code}"
    redeem_url = f"{_PORTAL_BASE}/invite?code={quote(code)}"

    text = f"""\
Hallo,

Sie wurden zum Portal der Wagner Hausverwaltung GmbH eingeladen.

Einladungscode:  {code}
E-Mail-Adresse:  {email}
Rolle:           {role}

Diese Einladung ist 14 Tage gültig.

Jetzt einlösen + Konto einrichten:
{redeem_url}

Falls der Link nicht funktioniert, öffnen Sie {_PORTAL_BASE}/invite und
geben Sie den Code oben ein.

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
<p style="margin: 24px 0;">
  <a href="{redeem_url}" \
style="display: inline-block; padding: 12px 22px; background: #1863DC; color: #fff; \
text-decoration: none; border-radius: 6px; font-weight: 600;">Einladung einlösen</a>
</p>
<p style="color: #666; font-size: 14px;">
  Falls der Button nicht funktioniert, öffnen Sie
  <a href="{_PORTAL_BASE}/invite">{_PORTAL_BASE}/invite</a> und geben Sie
  den Code oben ein.
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
