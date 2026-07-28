"""ReportLab generator for Versammlungsprotokoll PDFs in WHV design.

Output: a branded A4 protocol documenting a (manually created)
Versammlung — works for WEG *and* Mietverwaltungen, where Impower can't
create an ETV. Contents: a blue header band with the WHV logo, the
assembly + property identity, date/location, an optional description,
the full agenda (each TOP with its details, Beschlusstext and result),
and a signature block for the owner.

A *white* DocuSeal text tag — ``{{Unterschrift;type=signature}}`` — is
placed on the signature line. DocuSeal's ``/templates/pdf`` builds form
fields from text tags in the PDF, so this becomes the signature field
when the request is sent. Rendering it white means it leaves no visible
artifact if a DocuSeal version doesn't parse tags (ADR-0012 flags the
API shape as "verify against the deployed version").

Returned as raw bytes so callers can stream it or hand it to the
signature service. Rendering is synchronous (ReportLab is CPU-bound) —
async callers should wrap this in ``asyncio.to_thread()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BERLIN = ZoneInfo("Europe/Berlin")

# Brand palette — the app's AccentColor blue, matching the iOS app + the
# App Store marketing card so the printed protocol reads as "the same WHV".
_BRAND_BLUE = colors.HexColor("#1863DC")
_INK = colors.HexColor("#212121")
_MUTED = colors.HexColor("#4e4b66")
_HAIRLINE = colors.HexColor("#e0e0e0")

_LOGO_PATH = Path(__file__).parent / "assets" / "whv-logo.png"
_LOGO_ASPECT = 838 / 471  # trimmed logo width / height

_MARGIN = 18 * mm
_BAND_H = 30 * mm

# Lazily-built ImageReader for the logo, cached across renders. None if the
# asset is missing/unreadable — the header falls back to a text wordmark.
_logo_reader: ImageReader | None = None
_logo_tried = False


def _logo() -> ImageReader | None:
    global _logo_reader, _logo_tried
    if not _logo_tried:
        _logo_tried = True
        try:
            if _LOGO_PATH.exists():
                _logo_reader = ImageReader(str(_LOGO_PATH))
        except Exception:  # pragma: no cover - defensive, never crash a render
            _logo_reader = None
    return _logo_reader


@dataclass
class ProtocolAgendaItem:
    """One agenda point, with enum values pre-stringified to German labels
    by the caller so this module stays free of SQLAlchemy enum imports."""

    position: int
    title: str
    type_label: str
    body: str
    beschluss_text: str | None
    result_label: str | None
    vote_yes: int
    vote_no: int
    vote_abstain: int
    voting_basis_label: str | None
    present_count: int | None


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(_BERLIN).strftime("%d.%m.%Y %H:%M Uhr")


def _fmt_date(dt: datetime) -> str:
    return dt.astimezone(_BERLIN).strftime("%d.%m.%Y")


def _date_range(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "—"
    s = start.astimezone(_BERLIN)
    if end is None:
        return _fmt_dt(start)
    e = end.astimezone(_BERLIN)
    if s.date() == e.date():
        return f"{s.strftime('%d.%m.%Y')}, {s.strftime('%H:%M')} - {e.strftime('%H:%M')} Uhr"
    return f"{_fmt_dt(start)} - {_fmt_dt(end)}"


def _rich(text: str) -> str:
    """Escape user text for a ReportLab Paragraph + keep line breaks."""
    return escape(text).replace("\n", "<br/>")


def _draw_chrome(canvas, doc, *, title: str) -> None:  # type: ignore[no-untyped-def]
    """Per-page header band (logo + title) and footer (company + page)."""
    canvas.saveState()
    w, h = A4

    canvas.setFillColor(_BRAND_BLUE)
    canvas.rect(0, h - _BAND_H, w, _BAND_H, fill=1, stroke=0)

    logo = _logo()
    if logo is not None:
        lh = 16 * mm
        lw = lh * _LOGO_ASPECT
        canvas.drawImage(
            logo,
            _MARGIN,
            h - _BAND_H + (_BAND_H - lh) / 2,
            width=lw,
            height=lh,
            mask="auto",
            preserveAspectRatio=True,
        )
    else:
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(_MARGIN, h - _BAND_H / 2 - 5, "WAGNER HAUSVERWALTUNG GMBH")

    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawRightString(w - _MARGIN, h - _BAND_H / 2 - 5, title)

    canvas.setStrokeColor(_HAIRLINE)
    canvas.setLineWidth(0.5)
    canvas.line(_MARGIN, 15 * mm, w - _MARGIN, 15 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(_MARGIN, 10 * mm, "Wagner Hausverwaltung GmbH")
    canvas.drawRightString(w - _MARGIN, 10 * mm, f"Seite {doc.page}")
    canvas.restoreState()


def render_protocol_pdf(
    *,
    assembly_title: str,
    property_name: str,
    property_address: str | None,
    location: str | None,
    scheduled_start: datetime | None,
    scheduled_end: datetime | None,
    status_label: str,
    description: str,
    agenda_items: list[ProtocolAgendaItem],
    generated_at: datetime,
) -> bytes:
    """Render the WHV-branded Versammlungsprotokoll and return its bytes."""
    buffer = BytesIO()
    title = "Versammlungsprotokoll"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_BAND_H + 10 * mm,
        bottomMargin=22 * mm,
        title=f"{title}: {assembly_title}",
        author="Wagner Hausverwaltung GmbH",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, leading=20, textColor=_INK)
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=_BRAND_BLUE,
        spaceBefore=5 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontSize=10, leading=14, textColor=_INK
    )
    small = ParagraphStyle(
        "Small", parent=styles["BodyText"], fontSize=9, leading=12, textColor=_MUTED
    )
    top = ParagraphStyle("Top", parent=body, fontSize=11, leading=15, spaceBefore=3 * mm)

    story: list[Flowable] = [
        Paragraph(_rich(assembly_title), h1),
        Paragraph(f"<b>{_rich(property_name)}</b>", body),
    ]
    if property_address:
        story.append(Paragraph(_rich(property_address), small))
    story.append(Spacer(1, 4 * mm))

    meta_rows = [
        ["Datum / Uhrzeit", _date_range(scheduled_start, scheduled_end)],
        ["Ort", location or "—"],
        ["Status", status_label],
    ]
    meta_tbl = Table(meta_rows, colWidths=[40 * mm, 134 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), _INK),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(meta_tbl)

    if description.strip():
        story.append(Paragraph("Beschreibung", h2))
        story.append(Paragraph(_rich(description), body))

    story.append(Paragraph("Tagesordnung", h2))
    if not agenda_items:
        story.append(Paragraph("Es wurden keine Tagesordnungspunkte erfasst.", small))
    for it in agenda_items:
        block: list[Flowable] = [
            Paragraph(f"<b>TOP {it.position}: {_rich(it.title)}</b>", top),
            Paragraph(it.type_label, small),
        ]
        if it.body.strip():
            block.append(Paragraph(_rich(it.body), body))
        if it.beschluss_text and it.beschluss_text.strip():
            box = Table(
                [[Paragraph(f"<b>Beschluss:</b> {_rich(it.beschluss_text)}", body)]],
                colWidths=[174 * mm],
            )
            box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef3fe")),
                        ("LINEBEFORE", (0, 0), (0, -1), 3, _BRAND_BLUE),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            block.append(Spacer(1, 2 * mm))
            block.append(box)
        meta_bits: list[str] = []
        if it.result_label:
            meta_bits.append(f"Ergebnis: {it.result_label}")
        if it.vote_yes or it.vote_no or it.vote_abstain:
            meta_bits.append(f"Ja {it.vote_yes} · Nein {it.vote_no} · Enthaltung {it.vote_abstain}")
        if it.voting_basis_label:
            meta_bits.append(f"Stimmrecht: {it.voting_basis_label}")
        if it.present_count is not None:
            meta_bits.append(f"Anwesend: {it.present_count}")
        if meta_bits:
            block.append(Paragraph(" &nbsp;|&nbsp; ".join(escape(b) for b in meta_bits), small))
        story.append(KeepTogether([*block, Spacer(1, 3 * mm)]))

    # Signature block — white DocuSeal tags become the form fields.
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "Mit meiner Unterschrift bestätige ich den Inhalt dieses Protokolls.",
            small,
        )
    )
    story.append(Spacer(1, 2 * mm))
    sig_tbl = Table(
        [
            [
                Paragraph(
                    '<font color="#ffffff">{{Unterschrift;type=signature;required=true}}</font>',
                    body,
                ),
                Paragraph('<font color="#ffffff">{{Datum;type=date}}</font>', body),
            ],
            [
                Paragraph("Unterschrift Eigentümer/in", small),
                Paragraph("Ort, Datum", small),
            ],
        ],
        colWidths=[104 * mm, 70 * mm],
    )
    sig_tbl.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (0, 0), 0.7, _INK),
                ("LINEBELOW", (1, 0), (1, 0), 0.7, _INK),
                ("TOPPADDING", (0, 0), (-1, 0), 16 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]
        )
    )
    story.append(sig_tbl)

    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            f"Erstellt durch das Portal der Wagner Hausverwaltung GmbH "
            f"am {_fmt_date(generated_at)}. Zeitangaben in Europe/Berlin.",
            small,
        )
    )

    def _on_page(canvas, doc_):  # type: ignore[no-untyped-def]
        _draw_chrome(canvas, doc_, title=title)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def _signature_image(signature_png: bytes | None) -> Flowable:
    """Scale the owner's drawn signature into the block (max ~60x20 mm,
    aspect preserved). Falls back to blank space if no/invalid image so the
    line still renders."""
    if not signature_png:
        return Spacer(1, 18 * mm)
    try:
        img = Image(BytesIO(signature_png))
        iw, ih = float(img.imageWidth), float(img.imageHeight)
        if iw <= 0 or ih <= 0:
            return Spacer(1, 18 * mm)
        scale = min((60 * mm) / iw, (18 * mm) / ih)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        img.hAlign = "LEFT"
        return img
    except Exception:  # pragma: no cover - never let a bad image crash the render
        return Spacer(1, 18 * mm)


def render_vollmacht_pdf(
    *,
    principal_name: str,
    proxy_name: str,
    scope_note: str | None,
    assembly_title: str,
    property_name: str,
    property_address: str | None,
    assembly_start: datetime | None,
    signed_at: datetime,
    signature_png: bytes | None,
    voting_instructions: list[dict[str, Any]] | None = None,
) -> bytes:
    """Render a WHV-branded Vollmacht (proxy authorization) for one ETV,
    with the owner's in-app signature composited into the signature block.
    Returns the PDF bytes."""
    buffer = BytesIO()
    title = "Vollmacht"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_BAND_H + 10 * mm,
        bottomMargin=22 * mm,
        title=f"Vollmacht: {assembly_title}",
        author="Wagner Hausverwaltung GmbH",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("VH1", parent=styles["Heading1"], fontSize=16, leading=20, textColor=_INK)
    bodyst = ParagraphStyle(
        "VBody", parent=styles["BodyText"], fontSize=11, leading=16, textColor=_INK
    )
    small = ParagraphStyle(
        "VSmall", parent=styles["BodyText"], fontSize=9, leading=12, textColor=_MUTED
    )

    story: list[Flowable] = [
        Paragraph("Vollmacht zur Eigentümerversammlung", h1),
        Paragraph(f"<b>{_rich(property_name)}</b>", bodyst),
    ]
    if property_address:
        story.append(Paragraph(_rich(property_address), small))
    story.append(Spacer(1, 4 * mm))

    meta_rows = [
        ["Versammlung", assembly_title],
        ["Datum", _fmt_dt(assembly_start) if assembly_start else "—"],
    ]
    meta_tbl = Table(meta_rows, colWidths=[40 * mm, 134 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), _INK),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 6 * mm))

    authorization = (
        f"Hiermit bevollmächtige ich, <b>{_rich(principal_name)}</b>, "
        f"<b>{_rich(proxy_name)}</b>, mich in der oben genannten "
        f"Eigentümerversammlung zu vertreten und mein Stimmrecht in allen "
        f"Tagesordnungspunkten in meinem Namen auszuüben."
    )
    story.append(Paragraph(authorization, bodyst))

    # Per-TOP Weisungen — the binding half of the document, so it gets a real
    # table (TOP / Weisung) rather than a prose line.
    if voting_instructions:
        story.append(Spacer(1, 5 * mm))
        story.append(
            Paragraph(
                "<b>Weisungen zu den Tagesordnungspunkten</b><br/>"
                "Die bevollmächtigte Person ist bei den folgenden "
                "Tagesordnungspunkten an diese Weisung gebunden:",
                bodyst,
            )
        )
        story.append(Spacer(1, 3 * mm))
        rows: list[list[Any]] = [
            [
                Paragraph("<b>TOP</b>", small),
                Paragraph("<b>Tagesordnungspunkt</b>", small),
                Paragraph("<b>Weisung</b>", small),
            ]
        ]
        for entry in voting_instructions:
            rows.append(
                [
                    Paragraph(str(entry.get("position", "")), small),
                    Paragraph(_rich(str(entry.get("title", ""))), small),
                    Paragraph(f"<b>{_rich(str(entry.get('instruction', '')).title())}</b>", small),
                ]
            )
        weisung_tbl = Table(rows, colWidths=[14 * mm, 122 * mm, 38 * mm], repeatRows=1)
        weisung_tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, _INK),
                    ("LINEBELOW", (0, 1), (-1, -2), 0.25, _MUTED),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(weisung_tbl)

    if scope_note and scope_note.strip():
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"<b>Einschränkung / Weisung:</b> {_rich(scope_note)}", bodyst))

    story.append(Spacer(1, 14 * mm))
    sig_tbl = Table(
        [
            [_signature_image(signature_png)],
            [Paragraph(f"{_rich(principal_name)} &nbsp;·&nbsp; {_fmt_date(signed_at)}", small)],
        ],
        colWidths=[100 * mm],
    )
    sig_tbl.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (0, 0), 0.7, _INK),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("TOPPADDING", (0, 1), (0, 1), 2),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(sig_tbl)

    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            f"Digital erteilt über das Portal der Wagner Hausverwaltung GmbH "
            f"am {_fmt_dt(signed_at)}. Zeitangaben in Europe/Berlin.",
            small,
        )
    )

    def _on_page(canvas, doc_):  # type: ignore[no-untyped-def]
        _draw_chrome(canvas, doc_, title=title)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()
