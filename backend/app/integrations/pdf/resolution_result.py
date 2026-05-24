"""ReportLab generator for Umlaufbeschluss result PDFs.

Output: an A4 protocol PDF documenting the outcome of a closed resolution.
Contents: title, property, mode, dates, full tally counts, optional anonymized
vote ledger (vote count per choice — owner identities are NOT included in the
PDF, only aggregate counts plus the per-choice voted-at timestamps for audit).
Returned as raw bytes so callers can either save to disk or upload to S3.

We render synchronously — ReportLab is CPU-bound, not I/O — and the result
PDF for a single resolution typically fits in <50 KB / sub-second. Callers
from async code should wrap this in `asyncio.to_thread()`.
"""

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _fmt_berlin(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(_BERLIN).strftime("%d.%m.%Y %H:%M Uhr")


def render_result_pdf(
    *,
    resolution_title: str,
    property_name: str,
    mode_label: str,
    status_label: str,
    opens_at: datetime,
    closes_at: datetime,
    decided_at: datetime | None,
    eligible_voters: int,
    ja: int,
    nein: int,
    enthaltung: int,
    required_quorum: int,
    summary_line: str,
) -> bytes:
    """Render an A4 result protocol PDF and return its bytes.

    `mode_label` / `status_label` are the German enum values (e.g. KLASSISCH,
    ANGENOMMEN) — passed in pre-stringified so this module stays free of the
    SQLAlchemy enum imports and easy to unit-test.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Umlaufbeschluss-Protokoll: {resolution_title}",
        author="Wagner Hausverwaltung GmbH",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "WHV_H1",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1a1a1a"),
        spaceAfter=4 * mm,
    )
    h2 = ParagraphStyle(
        "WHV_H2",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#1a1a1a"),
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "WHV_Body",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#212121"),
    )
    small = ParagraphStyle(
        "WHV_Small",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#4e4b66"),
    )

    cast = ja + nein + enthaltung
    missing = max(0, eligible_voters - cast)
    accent = (
        colors.HexColor("#1B873F") if status_label == "ANGENOMMEN" else colors.HexColor("#B3261E")
    )

    story = [
        Paragraph("Protokoll Umlaufbeschluss", h1),
        Paragraph(f"<b>{resolution_title}</b>", body),
        Spacer(1, 4 * mm),
        Paragraph(f"Liegenschaft: {property_name}", body),
        Paragraph(f"Verfahren: {mode_label}", body),
        Spacer(1, 4 * mm),
        Paragraph("Fristen", h2),
    ]

    meta_rows = [
        ["Eröffnet am", _fmt_berlin(opens_at)],
        ["Fristende", _fmt_berlin(closes_at)],
        ["Beschlossen am", _fmt_berlin(decided_at)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[45 * mm, 110 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#4e4b66")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(meta_tbl)

    story.append(Paragraph("Stimmenzählung", h2))
    tally_rows = [
        ["Stimmberechtigte Eigentümer", str(eligible_voters)],
        ["Erforderliches Quorum", str(required_quorum) if required_quorum else "—"],
        ["Abgegebene Stimmen", str(cast)],
        ["Nicht abgegeben", str(missing)],
        ["JA", str(ja)],
        ["NEIN", str(nein)],
        ["Enthaltung", str(enthaltung)],
    ]
    tally_tbl = Table(tally_rows, colWidths=[80 * mm, 75 * mm])
    tally_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#4e4b66")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 3), (-1, 3), 0.5, colors.HexColor("#ebebeb")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(tally_tbl)

    story.append(Paragraph("Ergebnis", h2))
    result_tbl = Table(
        [[Paragraph(f"<b>{status_label}</b>", body)], [Paragraph(summary_line, body)]],
        colWidths=[155 * mm],
    )
    result_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f4f4")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(result_tbl)

    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "Erstellt automatisch durch das Portal der Wagner Hausverwaltung GmbH. "
            "Zeitangaben in Europe/Berlin.",
            small,
        )
    )

    doc.build(story)
    return buffer.getvalue()
