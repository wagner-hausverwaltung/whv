def render_password_reset_email(email: str, token: str, ttl_minutes: int) -> tuple[str, str, str]:
    """Returns (subject, html, text) for a password-reset email.

    German primary. Token is included verbatim in both bodies — once we have a
    web portal (Phase 3) or iOS app (Phase 2) we can switch to a deep link.
    """
    subject = "Passwort zurücksetzen — WHV-Portal"

    text = f"""\
Hallo,

Sie haben das Zurücksetzen des Passworts für Ihr WHV-Portal-Konto angefordert.

E-Mail-Adresse:  {email}
Token:           {token}
Gültigkeit:      {ttl_minutes} Minuten

Falls Sie diesen Vorgang nicht angefordert haben, ignorieren Sie diese E-Mail
einfach. Ihr Passwort bleibt unverändert.

Solange das Web-Portal noch nicht verfügbar ist, lösen Sie den Token mit
einem HTTP-Aufruf an /auth/reset-password ein (siehe API-Dokumentation).

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
<h1 style="font-size: 22px; margin-bottom: 16px;">Passwort zurücksetzen</h1>
<p>Hallo,</p>
<p>
  Sie haben das Zurücksetzen des Passworts für Ihr
  <strong>WHV-Portal-Konto</strong> angefordert.
</p>
<div style="background: #f5f5f5; border-left: 4px solid #1a1a1a; padding: 16px; margin: 24px 0;">
  <p style="margin: 0; font-size: 13px; color: #666;">Reset-Token (gültig {ttl_minutes} Minuten)</p>
  <p style="margin: 8px 0 0; font-size: 15px; font-family: ui-monospace, Menlo, monospace; \
word-break: break-all;">{token}</p>
</div>
<p>
  <strong>E-Mail-Adresse:</strong> {email}
</p>
<p style="color: #666; font-size: 14px;">
  Falls Sie diesen Vorgang nicht angefordert haben, ignorieren Sie diese
  E-Mail einfach. Ihr Passwort bleibt unverändert.
</p>
<p style="color: #666; font-size: 14px;">
  Solange das Web-Portal noch nicht verfügbar ist, lösen Sie den Token mit
  einem HTTP-Aufruf an <code>/auth/reset-password</code> ein.
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
