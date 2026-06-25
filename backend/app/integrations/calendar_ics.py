"""iCalendar (.ics, RFC 5545) export for a property's Liegenschafts-Kalender
(ADR-0018).

Hand-rolled (no extra dependency). ETV assemblies become *timed* VEVENTs with
the real start/end, location and Teams link; Winterdienst / Kehrwoche / Termin
events become *all-day* VEVENTs. Stable UIDs mean a re-import updates rather
than duplicates. Imports cleanly into Outlook, Apple Calendar and Google.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import CalendarEvent, CalendarEventType, EtvAssembly

_PRODID = "-//Wagner Hausverwaltung GmbH//WHV Kalender//DE"
_DOMAIN = "wagner-hausverwaltung.com"

_EVENT_LABEL = {
    CalendarEventType.WINTERDIENST: "Winterdienst",
    CalendarEventType.KEHRWOCHE: "Kehrwoche",
    CalendarEventType.TERMIN: "Termin",
}


def _escape(text: str) -> str:
    """Escape a TEXT value per RFC 5545 §3.3.11."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line to <=75 octets, continuation lines led by a space
    (RFC 5545 §3.1), without splitting a multi-byte UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out = bytearray()
    start, limit = 0, 75
    while len(raw) - start > limit:
        cut = start + limit
        while cut > start and (raw[cut] & 0xC0) == 0x80:  # don't split a code point
            cut -= 1
        out += raw[start:cut] + b"\r\n "
        start, limit = cut, 74  # the leading space counts toward the 75 octets
    out += raw[start:]
    return out.decode("utf-8")


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_property_calendar_ics(
    *,
    property_name: str,
    property_address: str | None,
    assemblies: list[EtvAssembly],
    events: list[CalendarEvent],
    now: datetime,
) -> str:
    stamp = _utc(now)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(property_name)}",
    ]

    for a in assemblies:
        summary = f"ETV: {a.title}" if a.title else "Eigentümerversammlung"
        location = a.location or property_address or property_name
        lines += [
            "BEGIN:VEVENT",
            f"UID:etv-{a.id}@{_DOMAIN}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_utc(a.scheduled_start)}",
            f"DTEND:{_utc(a.scheduled_end)}",
            f"SUMMARY:{_escape(summary)}",
        ]
        if location:
            lines.append(f"LOCATION:{_escape(location)}")
        if a.teams_meeting_url:
            lines.append(f"URL:{_escape(a.teams_meeting_url)}")
            lines.append(f"DESCRIPTION:{_escape('Microsoft Teams: ' + a.teams_meeting_url)}")
        lines.append("END:VEVENT")

    for e in events:
        label = e.title or _EVENT_LABEL.get(e.event_type, "Termin")
        summary = f"{label} - {e.assigned_label}" if e.assigned_label else label
        end_excl = (e.ends_on or e.starts_on) + timedelta(days=1)
        lines += [
            "BEGIN:VEVENT",
            f"UID:event-{e.id}@{_DOMAIN}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{e.starts_on.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end_excl.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(summary)}",
        ]
        if e.note:
            lines.append(f"DESCRIPTION:{_escape(e.note)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
