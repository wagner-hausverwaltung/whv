"""Template-overlay engine for the anfragen@ offer generator (ADR-0017).

The two offer templates are pre-printed PDFs whose per-customer fields we
*white-out and re-stamp* rather than regenerate from scratch — keeping every
other word of the (long, legal) document verbatim. This module is the generic
mechanism: given the base PDF bytes and a list of :class:`StampField`s, it

  1. builds a transparent ReportLab overlay canvas per page,
  2. paints a white rectangle over each old value (``cover``),
  3. draws the replacement string at the requested position,
  4. merges the overlay onto the base page with pypdf.

Coordinates are given in **top-left points** (the system ``pdftotext -bbox``
reports), because that is how the field maps were measured; we convert to
ReportLab's bottom-left origin internally. Only reportlab + pypdf are needed
(both already dependencies) — no new packages, no HTML-to-PDF engine.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pypdf
from reportlab.lib.colors import black, white
from reportlab.pdfgen import canvas

# Helvetica (WinAnsi) covers German umlauts + €, which is all the stamped
# values use. Matching the form's exact face isn't necessary for a handful of
# short values; matching size + baseline is what keeps it looking native.
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


@dataclass(frozen=True)
class StampField:
    """One value to white-out and (optionally) re-stamp on a page.

    All coordinates are in points, **top-left origin** (y grows downward),
    matching ``pdftotext -bbox`` output.
    """

    page: int  # 1-based page number
    text: str  # replacement string ("" = erase only, stamp nothing)
    x: float  # anchor x of the replacement text
    y_top: float  # top edge of the replacement text's line box
    size: float  # font size in points
    # White rectangle (x0, y0, x1, y1) painted before stamping; None = no cover.
    cover: tuple[float, float, float, float] | None = None
    bold: bool = False
    align: str = "left"  # "left" anchors at x, "right" anchors x as the right edge


def stamp_pdf(base_pdf: bytes, fields: list[StampField]) -> bytes:
    """Return ``base_pdf`` with every field whited-out and re-stamped."""
    reader = pypdf.PdfReader(io.BytesIO(base_pdf))
    by_page: dict[int, list[StampField]] = {}
    for f in fields:
        by_page.setdefault(f.page, []).append(f)

    writer = pypdf.PdfWriter()
    for idx, page in enumerate(reader.pages, start=1):
        page_fields = by_page.get(idx)
        if page_fields:
            mb = page.mediabox
            overlay = _render_overlay(
                float(mb.left), float(mb.bottom), float(mb.right), float(mb.top), page_fields
            )
            page.merge_page(overlay)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _render_overlay(
    left: float, bottom: float, right: float, top: float, fields: list[StampField]
) -> pypdf.PageObject:
    """Draw white-outs + stamps onto a one-page canvas, return it as a page.

    Field coordinates are top-left, measured relative to the page's MediaBox
    (as ``pdftotext -bbox`` reports). We convert to PDF user space, which is
    where pypdf's ``merge_page`` composites: ``user_x = left + x`` and
    ``user_y = top - y_top``. The canvas spans ``(right, top)`` so any point up
    to the MediaBox top is drawable even when the box doesn't start at y=0
    (the MV template's box starts at y≈7.83, which previously shifted every
    stamp down by that much).
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(right, top))

    # Pass 1: cover all old values first (so a stamp is never erased by a
    # later field's cover rectangle).
    c.setFillColor(white)
    for f in fields:
        if f.cover is not None:
            x0, y0, x1, y1 = f.cover
            c.rect(left + x0, top - y1, x1 - x0, y1 - y0, fill=1, stroke=0)

    # Pass 2: stamp the replacement text.
    c.setFillColor(black)
    for f in fields:
        if not f.text:
            continue
        c.setFont(_FONT_BOLD if f.bold else _FONT, f.size)
        # Baseline sits ~80 % down the line box from its top edge.
        baseline = top - f.y_top - f.size * 0.8
        x = left + f.x
        if f.align == "right":
            c.drawRightString(x, baseline, f.text)
        else:
            c.drawString(x, baseline, f.text)

    c.showPage()
    c.save()
    buf.seek(0)
    return pypdf.PdfReader(buf).pages[0]
