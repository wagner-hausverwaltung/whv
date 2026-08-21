"""Mails for the anfragen@ clarification round-trip.

Extraction can read units and address out of almost any inquiry, but the
contract type (WEG vs. Mietverwaltung/SEV) is often simply not stated — and
guessing it would attach the wrong Verwaltervertrag. Instead of leaving the
prospect with silence, we ask the one missing question and let their reply
re-run extraction.
"""

from __future__ import annotations

_SIGNATURE_TEXT = (
    "Mit freundlichen Grüßen\n"
    "Wagner Hausverwaltung GmbH\n"
    "Staufeneckstraße 17 · 70469 Stuttgart\n"
    "info@wagner-hausverwaltung.com"
)

_SIGNATURE_HTML = (
    "<p>Mit freundlichen Grüßen<br>"
    "<strong>Wagner Hausverwaltung GmbH</strong><br>"
    "Staufeneckstraße 17 · 70469 Stuttgart<br>"
    '<a href="mailto:info@wagner-hausverwaltung.com">info@wagner-hausverwaltung.com</a></p>'
)


def render_clarification_email(*, subject: str | None) -> tuple[str, str, str]:
    """(subject, html, text) asking which kind of Verwaltung is wanted.

    Kept to a single question: everything else we need (units, object) was
    already extracted, and a long form would cost replies.
    """
    ref = (subject or "").strip()
    subject_line = f"Rückfrage zu Ihrer Anfrage: {ref}" if ref else "Rückfrage zu Ihrer Anfrage"

    text = (
        "Guten Tag,\n\n"
        "vielen Dank für Ihre Anfrage — wir erstellen Ihnen gern ein Angebot.\n\n"
        "Damit wir Ihnen den passenden Verwaltervertrag zusenden können, fehlt uns "
        "noch eine Angabe: Geht es um\n\n"
        "  • die Verwaltung einer WEG (Wohnungseigentümergemeinschaft) oder\n"
        "  • um Mietverwaltung bzw. Sondereigentumsverwaltung (SEV)?\n\n"
        "Antworten Sie einfach auf diese E-Mail — ein Wort genügt. Das Angebot "
        "erhalten Sie dann automatisch.\n\n"
        f"{_SIGNATURE_TEXT}"
    )

    html = (
        "<p>Guten Tag,</p>"
        "<p>vielen Dank für Ihre Anfrage — wir erstellen Ihnen gern ein Angebot.</p>"
        "<p>Damit wir Ihnen den passenden Verwaltervertrag zusenden können, fehlt uns "
        "noch eine Angabe: Geht es um</p>"
        "<ul>"
        "<li>die Verwaltung einer <strong>WEG</strong> (Wohnungseigentümergemeinschaft) oder</li>"
        "<li>um <strong>Mietverwaltung</strong> bzw. Sondereigentumsverwaltung (SEV)?</li>"
        "</ul>"
        "<p>Antworten Sie einfach auf diese E-Mail — ein Wort genügt. "
        "Das Angebot erhalten Sie dann automatisch.</p>"
        f"{_SIGNATURE_HTML}"
    )
    return subject_line, html, text


def render_review_notice(
    *,
    sender_email: str,
    subject: str | None,
    units: int | None,
    object_address: str | None,
    asked_back: bool,
) -> tuple[str, str, str]:
    """(subject, html, text) telling the Verwalter an inquiry needs a decision."""
    ref = (subject or "(ohne Betreff)").strip()
    subject_line = f"Anfrage braucht Prüfung: {ref}"
    detail = " · ".join(
        p
        for p in (
            f"{units} Einheiten" if units else None,
            object_address or None,
        )
        if p
    )
    followup = (
        "Der Interessent wurde automatisch nach der Verwaltungsart gefragt; "
        "sobald er antwortet, geht das Angebot von selbst raus."
        if asked_back
        else "Es wurde KEINE automatische Rückfrage verschickt."
    )
    text = (
        f"Neue Anfrage von {sender_email}, die nicht automatisch beantwortet werden konnte.\n\n"
        f"Betreff: {ref}\n"
        f"{detail}\n\n"
        f"{followup}\n\n"
        "Zur Bearbeitung: Admin → Anfragen\n"
    )
    html = (
        f"<p>Neue Anfrage von <strong>{sender_email}</strong>, die nicht automatisch "
        "beantwortet werden konnte.</p>"
        f"<p>Betreff: {ref}<br>{detail}</p>"
        f"<p>{followup}</p>"
        "<p>Zur Bearbeitung: Admin → Anfragen</p>"
    )
    return subject_line, html, text
