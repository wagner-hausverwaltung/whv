"""ReportLab generator for the Liegenschafts-Kalender PDF (ADR-0018).

A branded A4 month grid (Mo-So columns, weeks as rows) listing the
property's events for one month — Winterdienst / Kehrwoche assignments,
generic Termine, and the ETV date(s). Reuses the WHV header chrome from
`assembly_document` so it reads as the same brand.

Rendering is synchronous (ReportLab is CPU-bound) — async callers wrap it
in ``asyncio.to_thread()``.
"""

from __future__ import annotations

import calendar as _calmod
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.integrations.pdf.assembly_document import (
    _BAND_H,
    _BRAND_BLUE,
    _INK,
    _MARGIN,
    _MUTED,
    _draw_chrome,
)

_BERLIN = ZoneInfo("Europe/Berlin")

# Per-kind accent colours.
_KIND_COLOR = {
    "ETV": _BRAND_BLUE,
    "WINTERDIENST": colors.HexColor("#0e7490"),
    "KEHRWOCHE": colors.HexColor("#15803d"),
    "TERMIN": colors.HexColor("#6b7280"),
}
_KIND_LABEL = {
    "ETV": "Eigentümerversammlung",
    "WINTERDIENST": "Winterdienst",
    "KEHRWOCHE": "Kehrwoche",
    "TERMIN": "Termin",
}
_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_MONTHS = [
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


@dataclass
class CalendarPdfEntry:
    kind: str  # ETV / WINTERDIENST / KEHRWOCHE / TERMIN
    title: str
    starts_on: date
    ends_on: date | None
    assigned: str | None


def _covers(entry: CalendarPdfEntry, day: date) -> bool:
    end = entry.ends_on or entry.starts_on
    return entry.starts_on <= day <= end


def _legend_item(kind: str) -> str:
    hexc = _KIND_COLOR.get(kind, _MUTED).hexval()[2:]
    return f'<font color="#{hexc}">■</font> {_KIND_LABEL.get(kind, kind)}'


def render_calendar_pdf(
    *,
    year: int,
    month: int,
    property_name: str,
    property_address: str | None,
    entries: list[CalendarPdfEntry],
    generated_at: datetime,
) -> bytes:
    """Render the month grid and return PDF bytes."""
    buffer = BytesIO()
    title = "Kalender"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_BAND_H + 10 * mm,
        bottomMargin=20 * mm,
        title=f"Kalender {_MONTHS[month - 1]} {year}: {property_name}",
        author="Wagner Hausverwaltung GmbH",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("CH1", parent=styles["Heading1"], fontSize=15, leading=19, textColor=_INK)
    small = ParagraphStyle(
        "CSmall", parent=styles["BodyText"], fontSize=9, leading=12, textColor=_MUTED
    )
    head = ParagraphStyle(
        "CHead",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=1,
        fontName="Helvetica-Bold",
    )
    cell = ParagraphStyle(
        "CCell", parent=styles["BodyText"], fontSize=6.5, leading=8, textColor=_INK
    )

    story: list[Flowable] = [
        Paragraph(f"{_MONTHS[month - 1]} {year}", h1),
        Paragraph(f"<b>{escape(property_name)}</b>", small),
    ]
    if property_address:
        story.append(Paragraph(escape(property_address), small))
    story.append(Spacer(1, 4 * mm))

    # Header row + one row per ISO week.
    col_w = (A4[0] - 2 * _MARGIN) / 7.0
    grid: list[list[Flowable]] = [[Paragraph(d, head) for d in _WEEKDAYS]]
    for week in _calmod.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row: list[Flowable] = []
        for daynum_int in week:
            if daynum_int == 0:
                row.append(Paragraph("", cell))
                continue
            day = date(year, month, daynum_int)
            todays = [e for e in entries if _covers(e, day)]
            parts = [f'<font name="Helvetica-Bold" size="8">{daynum_int}</font>']
            for e in todays[:3]:
                color = _KIND_COLOR.get(e.kind, _MUTED)
                label = escape(e.title)[:22]
                parts.append(f'<font color="#{color.hexval()[2:]}" size="6">■ {label}</font>')
            if len(todays) > 3:
                parts.append(f'<font size="6" color="999999">+{len(todays) - 3}</font>')
            row.append(Paragraph("<br/>".join(parts), cell))
        grid.append(row)

    n_weeks = len(grid) - 1
    table = Table(
        grid,
        colWidths=[col_w] * 7,
        rowHeights=[7 * mm] + [25 * mm] * n_weeks,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BRAND_BLUE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d4d4d4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 1), (-1, -1), 3),
            ]
        )
    )
    story.append(table)

    # Legend — only the kinds actually present.
    story.append(Spacer(1, 4 * mm))
    present = sorted({e.kind for e in entries}, key=lambda k: list(_KIND_LABEL).index(k))
    if present:
        legend = " &nbsp;&nbsp; ".join(_legend_item(k) for k in present)
        story.append(Paragraph(legend, small))

    # Assignment list under the grid for printing/handing out.
    assigned = [e for e in entries if e.assigned]
    if assigned:
        story.append(Spacer(1, 3 * mm))
        for e in sorted(assigned, key=lambda x: x.starts_on):
            span = e.starts_on.strftime("%d.%m.")
            if e.ends_on and e.ends_on != e.starts_on:
                span += f"-{e.ends_on.strftime('%d.%m.')}"
            story.append(
                Paragraph(
                    f"<b>{span}</b> &nbsp; {escape(_KIND_LABEL.get(e.kind, e.kind))}: "
                    f"{escape(e.title)} — <b>{escape(e.assigned or '')}</b>",
                    small,
                )
            )

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            f"Erstellt durch das Portal der Wagner Hausverwaltung GmbH am "
            f"{generated_at.astimezone(_BERLIN).strftime('%d.%m.%Y')}.",
            small,
        )
    )

    def _on_page(canvas, doc_):  # type: ignore[no-untyped-def]
        _draw_chrome(canvas, doc_, title=title)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()
