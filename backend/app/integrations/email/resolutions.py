"""Email templates for Umlaufbeschluss notifications.

Two renderers:

  render_invitation_email — sent when a Verwalter creates an OFFEN resolution.
    Fans out to every eligible owner with a WHV-Portal account.

  render_result_email — sent by the Celery beat task after auto-tally.
    Includes the outcome line + a deep link to the detail page so the owner
    can download the result PDF.

Both return (subject, html, text). German primary; plain-text fallback below
the HTML for accessibility tools and clients that don't render HTML.
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


def render_invitation_email(
    *,
    resolution_title: str,
    property_name: str,
    closes_at: datetime,
    description: str,
    resolution_id: str,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for a new-Umlaufbeschluss invitation."""
    deadline = _fmt_berlin(closes_at)
    link = f"{_PORTAL_BASE}/resolutions/{resolution_id}"
    subject = f"Umlaufbeschluss: {resolution_title} — Frist {deadline}"

    text = f"""\
Hallo,

es liegt ein neuer Umlaufbeschluss zur Abstimmung vor:

  Beschluss:   {resolution_title}
  Liegenschaft: {property_name}
  Frist:        {deadline}

  ----- Beschlusstext -----
{description}
  -------------------------

Bitte stimmen Sie über das WHV-Portal ab:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    description_html = _escape_html(description)
    title_html = _escape_html(resolution_title)
    property_html = _escape_html(property_name)

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px;">Neuer Umlaufbeschluss</h1>
<p><strong>{title_html}</strong></p>
<p style="color: #4e4b66; font-size: 14px;">
  Liegenschaft: {property_html}<br>
  <strong>Frist: {deadline}</strong>
</p>

<div style="background: #f4f4f4; border-left: 4px solid #1863DC; \
padding: 12px 16px; margin: 20px 0; font-size: 14px; line-height: 1.5;">
  {description_html}
</div>

<p style="margin: 24px 0;">
  <a href="{link}" \
style="display: inline-block; padding: 10px 20px; background: #1863DC; color: #fff; \
text-decoration: none; border-radius: 6px; font-weight: 600;">Jetzt abstimmen</a>
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


def render_result_email(
    *,
    resolution_title: str,
    property_name: str,
    outcome_label: str,
    summary: str,
    resolution_id: str,
) -> tuple[str, str, str]:
    """Returns (subject, html, text) for a tallied-result notification.

    `outcome_label` is the German status word (ANGENOMMEN / ABGELEHNT).
    `summary` is the free-text tally line produced by _summarize_result in
    app/api/v1/circular.py — already includes JA/NEIN/Enthaltung counts.
    """
    link = f"{_PORTAL_BASE}/resolutions/{resolution_id}"
    subject = f"Umlaufbeschluss {outcome_label}: {resolution_title}"

    text = f"""\
Hallo,

die Abstimmung zum folgenden Umlaufbeschluss ist abgeschlossen:

  Beschluss:    {resolution_title}
  Liegenschaft: {property_name}
  Ergebnis:     {outcome_label}

  {summary}

Das Ergebnisprotokoll können Sie über das WHV-Portal einsehen:
{link}

Bei Fragen: support@wagner-hausverwaltung.com

Mit freundlichen Grüßen,
Wagner Hausverwaltung GmbH
"""

    title_html = _escape_html(resolution_title)
    property_html = _escape_html(property_name)
    summary_html = _escape_html(summary)
    accent = "#1B873F" if outcome_label == "ANGENOMMEN" else "#B3261E"

    html = f"""\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; \
max-width: 560px; margin: 0 auto; padding: 24px; color: #212121;">
<h1 style="font-size: 20px; margin-bottom: 16px;">
  Umlaufbeschluss <span style="color: {accent};">{outcome_label}</span>
</h1>
<p><strong>{title_html}</strong></p>
<p style="color: #4e4b66; font-size: 14px;">Liegenschaft: {property_html}</p>

<div style="background: #f4f4f4; border-left: 4px solid {accent}; \
padding: 12px 16px; margin: 20px 0; font-size: 14px; line-height: 1.5;">
  {summary_html}
</div>

<p style="margin: 24px 0;">
  <a href="{link}" \
style="display: inline-block; padding: 10px 20px; background: #1863DC; color: #fff; \
text-decoration: none; border-radius: 6px; font-weight: 600;">Protokoll ansehen</a>
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
