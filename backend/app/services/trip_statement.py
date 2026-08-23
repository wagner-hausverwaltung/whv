"""Kilometergeld-Abrechnung as PDF (ADR-0020).

One statement per month and driver: every trip with date, object, purpose,
km and amount, the month total, and a second block that regroups the
billable km per property (internal attribution; what a WEG may actually be
charged is contract-dependent — see services/trip_invoice.py). The payee is
the car's private owner, not necessarily the driver. Rendered with reportlab like the offer
documents; pure function of the trips passed in, so it is trivially
testable and the endpoint just streams the bytes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.models import Trip, TripPurpose

_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"

_PURPOSE_LABEL = {
    TripPurpose.BESICHTIGUNG.value: "Besichtigung",
    TripPurpose.ETV.value: "Eigentümerversammlung",
    TripPurpose.HANDWERKERTERMIN.value: "Handwerkertermin",
    TripPurpose.EIGENTUEMERTERMIN.value: "Eigentümertermin",
    TripPurpose.BUERO.value: "Büro",
    TripPurpose.SONSTIGES.value: "Sonstiges",
    TripPurpose.PRIVAT.value: "Privat",
}


@dataclass(frozen=True)
class StatementRow:
    trip: Trip
    property_name: str | None
    # Besichtigung of a prospect: the object is not a property yet, so the
    # statement prints the inquiry's address instead ("Anfrage: …"). Such
    # trips are WHV's own acquisition cost — they stay out of the per-WEG
    # Auslagen block and fall under "(ohne Objekt)".
    inquiry_address: str | None = None

    @property
    def object_label(self) -> str:
        if self.property_name:
            return self.property_name
        if self.inquiry_address:
            return f"Anfrage: {self.inquiry_address}"
        return "—"


def de_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    groups: list[str] = []
    w = str(whole)
    while len(w) > 3:
        groups.insert(0, w[-3:])
        w = w[:-3]
    groups.insert(0, w)
    return f"{sign}{'.'.join(groups)},{frac:02d} €"


def de_km(meters: int | None) -> str:
    return f"{Decimal(meters or 0) / 1000:.1f}".replace(".", ",") + " km"


def _month_label(month: str) -> str:
    names = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    y, m = (int(p) for p in month.split("-", 1))
    return f"{names[m - 1]} {y}"


def _fit(text: str, width: float, size: float) -> str:
    """Ellipsize to the column width — a statement must stay one row per trip."""
    if stringWidth(text, _FONT, size) <= width:
        return text
    while text and stringWidth(text + "…", _FONT, size) > width:
        text = text[:-1]
    return text + "…"


def render_statement(
    *,
    rows: list[StatementRow],
    month: str,
    driver_label: str,
    rate_cents_per_km: int,
    payee_label: str | None = None,
    generated_at: datetime | None = None,
) -> bytes:
    """Render the monthly Kilometergeld statement. Trips are listed in the
    order given (callers pass them chronologically). `payee_label` names who
    is reimbursed — the private owner of the car, which is not necessarily
    the driver."""
    _, page_h = A4
    margin = 18 * mm
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Fahrtenbuch {month}: {driver_label}")

    # Column layout (pt): Datum | Zeit | Objekt | Zweck | km | Betrag
    cols = [
        ("Datum", 52, "left"),
        ("Zeit", 62, "left"),
        ("Objekt", 168, "left"),
        ("Zweck", 110, "left"),
        ("km", 48, "right"),
        ("Betrag", 62, "right"),
    ]
    table_w = sum(w for _, w, _ in cols)
    x0 = margin
    size = 8.5
    lead = 12.0

    def header(first: bool) -> float:
        y: float = float(page_h) - margin
        c.setFont(_BOLD, 14 if first else 11)
        c.drawString(x0, y, f"Fahrtenbuch: Kilometergeld {_month_label(month)}")
        c.setFont(_FONT, 9)
        y -= 14
        c.drawString(x0, y, f"Fahrer: {driver_label}")
        c.drawRightString(
            x0 + table_w,
            y,
            f"Satz {Decimal(rate_cents_per_km) / 100:.2f} € je km".replace(".", ","),
        )
        if payee_label:
            y -= 12
            c.drawString(x0, y, f"Zahlungsempfänger (Fahrzeughalter): {payee_label}")
        if first:
            y -= 12
            c.setFont(_FONT, 7.5)
            c.drawString(
                x0,
                y,
                "Privatwagen des Zahlungsempfängers, Kilometerpauschale. "
                "Private Fahrten sind aufgeführt, aber nicht vergütet.",
            )
        y -= 16
        # table head
        c.setFillColorRGB(0.93, 0.93, 0.93)
        c.rect(x0, y - 4, table_w, 13, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(_BOLD, size)
        x = x0
        for title, w, align in cols:
            if align == "right":
                c.drawRightString(x + w - 2, y, title)
            else:
                c.drawString(x + 2, y, title)
            x += w
        return y - lead - 2

    def footer() -> None:
        c.setFont(_FONT, 7)
        stamp = (generated_at or datetime.now()).strftime("%d.%m.%Y %H:%M")
        c.drawString(x0, margin - 6, f"Erstellt {stamp} · Wagner Hausverwaltung GmbH")
        c.drawRightString(x0 + table_w, margin - 6, f"Seite {c.getPageNumber()}")

    y = header(first=True)
    total_m = 0
    total_cents = 0
    billable_m = 0
    by_prop: dict[str, tuple[int, int, int]] = defaultdict(lambda: (0, 0, 0))

    for r in rows:
        t = r.trip
        if y < margin + 30:
            footer()
            c.showPage()
            y = header(first=False)
        c.setFont(_FONT, size)
        start_local = t.started_at
        ended = t.ended_at
        time_txt = start_local.strftime("%H:%M") + (f"-{ended.strftime('%H:%M')}" if ended else "")
        purpose_txt = _PURPOSE_LABEL.get(t.purpose or "", "offen")
        cells = [
            start_local.strftime("%d.%m.%Y"),
            time_txt,
            _fit(r.object_label, cols[2][1] - 4, size),
            _fit(purpose_txt, cols[3][1] - 4, size),
            de_km(t.distance_m),
            de_money(t.amount_cents),
        ]
        x = x0
        for (_title, w, align), txt in zip(cols, cells, strict=True):
            if align == "right":
                c.drawRightString(x + w - 2, y, txt)
            else:
                c.drawString(x + 2, y, txt)
            x += w
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.3)
        c.line(x0, y - 3.5, x0 + table_w, y - 3.5)
        y -= lead
        total_m += t.distance_m or 0
        total_cents += t.amount_cents
        if t.is_billable:
            billable_m += t.distance_m or 0
            key = r.property_name or "(ohne Objekt)"
            n, m_, cts = by_prop[key]
            by_prop[key] = (n + 1, m_ + (t.distance_m or 0), cts + t.amount_cents)

    # Totals
    if y < margin + 60:
        footer()
        c.showPage()
        y = header(first=False)
    y -= 4
    c.setFont(_BOLD, size + 0.5)
    c.drawString(x0 + 2, y, f"Summe ({len(rows)} Fahrten)")
    c.drawRightString(x0 + sum(w for _, w, _ in cols[:5]) - 2, y, de_km(total_m))
    c.drawRightString(x0 + table_w - 2, y, de_money(total_cents))
    y -= lead
    c.setFont(_FONT, 7.5)
    c.drawString(x0 + 2, y, f"davon abrechenbar: {de_km(billable_m)}")
    y -= lead * 1.6

    # Auslagen per property
    if by_prop:
        if y < margin + 60:
            footer()
            c.showPage()
            y = header(first=False)
        c.setFont(_BOLD, 10)
        c.drawString(x0, y, "Auslagen je Objekt (Fahrtkosten Verwaltung ↔ Objekt)")
        y -= lead * 1.2
        c.setFont(_BOLD, size)
        c.drawString(x0 + 2, y, "Objekt")
        c.drawRightString(x0 + 300, y, "Fahrten")
        c.drawRightString(x0 + 380, y, "km")
        c.drawRightString(x0 + table_w - 2, y, "Betrag")
        y -= lead
        c.setFont(_FONT, size)
        for name, (n, m_, cts) in sorted(by_prop.items(), key=lambda kv: -kv[1][2]):
            if y < margin + 20:
                footer()
                c.showPage()
                y = header(first=False)
                c.setFont(_FONT, size)
            c.drawString(x0 + 2, y, _fit(name, 240, size))
            c.drawRightString(x0 + 300, y, str(n))
            c.drawRightString(x0 + 380, y, de_km(m_))
            c.drawRightString(x0 + table_w - 2, y, de_money(cts))
            y -= lead

    footer()
    c.showPage()
    c.save()
    return buf.getvalue()


def statement_filename(month: str, driver_label: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in driver_label.split("@")[0])
    return f"Fahrtenbuch-{month}-{safe}.pdf"


__all__ = ["StatementRow", "de_km", "de_money", "render_statement", "statement_filename"]

# date is imported for callers' type hints; keep the name referenced.
_ = date
