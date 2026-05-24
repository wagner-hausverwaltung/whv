def render_password_reset_email(
    email: str,
    token: str,
    ttl_minutes: int,
    reset_url: str,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for a password-reset email.

    German primary. The clickable `reset_url` is the per-environment portal
    deep link (e.g. https://portal.wagner-hausverwaltung.com/reset-password?token=...).
    The raw token is also shown as a fallback for users who can't follow the link
    (curl, suspicious mail clients).
    """
    subject = "Passwort zurücksetzen — WHV-Portal"

    text = f"""\
Hallo,

Sie haben das Zurücksetzen des Passworts für Ihr WHV-Portal-Konto angefordert.

E-Mail-Adresse:  {email}
Gültigkeit:      {ttl_minutes} Minuten

Klicken Sie auf den folgenden Link, um ein neues Passwort zu setzen:

  {reset_url}

Falls der Link nicht funktioniert, lösen Sie den Token manuell über einen
HTTP-Aufruf an /auth/reset-password ein:

  Token:  {token}

Falls Sie diesen Vorgang nicht angefordert haben, ignorieren Sie diese E-Mail
einfach. Ihr Passwort bleibt unverändert.

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
<p style="margin: 24px 0;">
  <a href="{reset_url}" style="display: inline-block; padding: 12px 24px; \
background: #1a1a1a; color: #fff; text-decoration: none; border-radius: 6px; \
font-weight: 600;">Neues Passwort setzen</a>
</p>
<p style="color: #666; font-size: 14px;">
  Link gültig {ttl_minutes} Minuten. Funktioniert der Button nicht?
  Kopieren Sie diese URL in Ihren Browser:
  <br>
  <span style="font-family: ui-monospace, Menlo, monospace; word-break: break-all; \
font-size: 13px; color: #1a1a1a;">{reset_url}</span>
</p>
<p>
  <strong>E-Mail-Adresse:</strong> {email}
</p>
<details style="margin: 16px 0; color: #666; font-size: 13px;">
  <summary>Token manuell einlösen (API)</summary>
  <p style="margin-top: 8px;">
    Falls der Link nicht funktioniert, lösen Sie den Token über einen
    HTTP-Aufruf an <code>/auth/reset-password</code> ein:
  </p>
  <pre style="background: #f5f5f5; padding: 12px; border-radius: 4px; font-size: 12px; \
overflow-x: auto;">{token}</pre>
</details>
<p style="color: #666; font-size: 14px;">
  Falls Sie diesen Vorgang nicht angefordert haben, ignorieren Sie diese
  E-Mail einfach. Ihr Passwort bleibt unverändert.
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
