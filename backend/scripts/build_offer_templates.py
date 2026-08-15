"""Build the committed MV/SEV offer templates from the VDIV 2026 sources.

One-off asset builder — run locally when VDIV publishes a new contract
generation, never at runtime. For each product line (MV, SEV) and variant
(Verbraucher, Unternehmer) it assembles:

    [ VDIV Verwaltervertrag, AcroForm-flattened ]
  + [ Anlage 1: Leistungsverzeichnis (Kompaktfassung) + Stundensätze,
      rendered from the VDIV xlsx with WHV's agreed terms ]
  + [ DKB Treuhandkonto-Verifizierung (blanked, WHV-prefilled) ]

and writes app/integrations/pdf/assets/offer_templates/{line}_{variant}_template.pdf.

Flattening matters: the VDIV PDFs carry 51-71 AcroForm fields, and form
annotations render ABOVE overlay stamps (learned the hard way on the WEG
template) — `gs -dPreserveAnnots=false` bakes them into the page.

WHV terms baked into Anlage 1 (confirmed 2026-08-15):
  - every VV row is "nach Aufwand" (no per-service Pauschalen)
  - GL rows are always vereinbart; BL rows are not owed
  - Stundensätze: see _STUNDENSAETZE below

Usage (openpyxl is not a backend dependency — point PYTHONPATH at any
site-packages that has it):

    PYTHONPATH=/path/with/openpyxl .venv/bin/python scripts/build_offer_templates.py \
        --mv-dir "~/Downloads/37_26_2026_VDIV-Verwaltervertrag_Mietverwaltung" \
        --sev-dir "~/Downloads/37_26_2026_VDIV-Verwaltervertrag_SEV"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

REPO_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_BACKEND))

from app.integrations.pdf.offer_overlay import StampField, stamp_pdf  # noqa: E402

ASSET_DIR = REPO_BACKEND / "app" / "integrations" / "pdf" / "assets" / "offer_templates"

# Static Verwalter block stamped into the template at build time (page 1,
# "und ... — nachstehend Verwalter genannt —").
_WHV_NAME = "Wagner Hausverwaltung GmbH"
_WHV_ADDRESS = "Staufeneckstraße 17, 70469 Stuttgart"

# Net hourly rates agreed 2026-08-15; gross derived at 19% in the render.
# Ingenieur / Auszubildende are not staffed at WHV and are omitted.
_STUNDENSAETZE: list[tuple[str, int]] = [
    ("Inhaber / Geschäftsführer / Prokurist", 120),
    ("Techniker", 95),
    ("Sachbearbeiter", 85),
    ("Sekretariat / Schreibkräfte", 65),
]

_VAT = 0.19

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


@dataclass(frozen=True)
class LvRow:
    pos: str
    bereich: str
    leistung: str
    beschreibung: str
    kat: str  # GL | VV | BL


def read_lv_rows(xlsx_path: Path) -> list[LvRow]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Leistungsverzeichnis"]
    rows: list[LvRow] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        pos, bereich, leistung, beschreibung, kat = raw[:5]
        if pos is None or kat not in ("GL", "VV", "BL"):
            continue
        rows.append(
            LvRow(
                pos=str(pos),
                bereich=str(bereich or "").strip(),
                leistung=str(leistung or "").strip(),
                beschreibung=" ".join(str(beschreibung or "").split()),
                kat=str(kat),
            )
        )
    if not rows:
        raise SystemExit(f"no Leistungsverzeichnis rows found in {xlsx_path}")
    return rows


def _vereinbart(kat: str) -> str:
    return {"GL": "ja (stets)", "VV": "ja", "BL": "nein"}[kat]


def _verguetungsart(kat: str) -> str:
    return {
        "GL": "Grundvergütung",
        "VV": "nach Aufwand (Stundensätze)",
        "BL": "gesonderte Vereinbarung",
    }[kat]


def _wrap(text: str, width: float, size: float, font: str = _FONT) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if stringWidth(cand, font, size) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def render_anlage(line_label: str, rows: list[LvRow]) -> bytes:
    """Anlage 1 as landscape A4: the Leistungsverzeichnis table, then the
    Stundensätze block. Layout is ours; content is verbatim VDIV."""
    page_w, page_h = landscape(A4)
    margin = 15 * mm
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    cols = [  # (heading, width in pt)
        ("Pos.", 30),
        ("Leistungsbereich", 100),
        ("Leistung", 150),
        ("Beschreibung / Hinweise", 280),
        ("Kat.", 26),
        ("Vereinbart", 52),
        ("Vergütungsart", 130),
    ]
    table_w = sum(w for _, w in cols)
    size = 7.0
    lead = 8.4
    header_h = 14.0

    def page_head(title: str) -> float:
        c.setFont(_FONT_BOLD, 11)
        c.drawString(margin, page_h - margin, f"Anlage 1 zum Verwaltervertrag — {title}")
        c.setFont(_FONT, 7.5)
        legend = (
            "Leistungsverzeichnis (Kompaktfassung) · GL = Grundleistung, mit der monatlichen "
            "Grundvergütung abgegolten · VV = variable Vergütung, auf Weisung des Eigentümers, "
            "nach Aufwand gemäß Stundensätzen · BL = besondere Leistung, nicht geschuldet"
        )
        y_line = page_h - margin - 11
        for line in _wrap(legend, table_w, 7.5):
            c.drawString(margin, y_line, line)
            y_line -= 9
        return y_line - 6

    def table_header(y: float) -> float:
        c.setFillColorRGB(0.92, 0.92, 0.92)
        c.rect(margin, y - header_h, table_w, header_h, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(_FONT_BOLD, size)
        x = margin
        for head, w in cols:
            c.drawString(x + 2, y - header_h + 4, head)
            x += w
        return y - header_h

    y = page_head(line_label)
    y = table_header(y)

    for row in rows:
        cells = [
            row.pos,
            row.bereich,
            row.leistung,
            row.beschreibung,
            row.kat,
            _vereinbart(row.kat),
            _verguetungsart(row.kat),
        ]
        wrapped = [_wrap(text, w - 4, size) for text, (_, w) in zip(cells, cols, strict=True)]
        row_h = max(len(ls) for ls in wrapped) * lead + 4
        if y - row_h < margin + 10:
            c.showPage()
            y = page_head(line_label)
            y = table_header(y)
        c.setFont(_FONT, size)
        x = margin
        for lines, (_, w) in zip(wrapped, cols, strict=True):
            for i, ln in enumerate(lines):
                c.drawString(x + 2, y - lead * (i + 1) + 1.5, ln)
            x += w
        y -= row_h
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.setLineWidth(0.4)
        c.line(margin, y, margin + table_w, y)

    # --- Stundensätze block ---------------------------------------------
    need = 30 + len(_STUNDENSAETZE) * 13 + 30
    if y - need < margin:
        c.showPage()
        y = page_head(line_label)
    y -= 22
    c.setFont(_FONT_BOLD, 9.5)
    c.drawString(margin, y, "Stundensätze")
    y -= 12
    c.setFont(_FONT, 7.5)
    c.drawString(
        margin,
        y,
        "Die Stundensätze gelten für alle Leistungen, die nach Aufwand abgerechnet werden "
        "(Bestandteil des Vertrags).",
    )
    y -= 16
    c.setFont(_FONT_BOLD, size + 0.5)
    c.drawString(margin + 2, y, "Funktion")
    c.drawRightString(margin + 330, y, "Stundensatz netto (EUR)")
    c.drawRightString(margin + 440, y, "Stundensatz brutto (EUR)")
    y -= 4
    c.setStrokeColorRGB(0.5, 0.5, 0.5)
    c.line(margin, y, margin + 450, y)
    for funktion, netto in _STUNDENSAETZE:
        y -= 13
        c.setFont(_FONT, size + 0.5)
        c.drawString(margin + 2, y, funktion)
        c.drawRightString(margin + 330, y, f"{netto:.2f}".replace(".", ","))
        brutto = round(netto * (1 + _VAT), 2)
        c.drawRightString(margin + 440, y, f"{brutto:.2f}".replace(".", ","))
    y -= 14
    c.setFont(_FONT, 6.5)
    c.drawString(margin, y, "USt-Satz 19 %. Quelle Leistungskatalog: VDIV Deutschland, 2026.")

    c.save()
    return buf.getvalue()


@dataclass(frozen=True)
class Widget:
    page: int
    x: float
    y_top: float  # top edge, top-left origin
    h: float
    is_text: bool
    label: str  # words on the same line, left of the widget
    context: str  # tail of the line above


def _read_widgets(pdf: Path) -> list[Widget]:
    xml = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"], check=True, capture_output=True
    ).stdout
    ns = "{http://www.w3.org/1999/xhtml}"
    pages_words: list[list[tuple[float, float, float, float, str]]] = []
    for page in ET.fromstring(xml).iter(f"{ns}page"):
        pages_words.append(
            [
                (
                    float(w.get("xMin")),
                    float(w.get("yMin")),
                    float(w.get("xMax")),
                    float(w.get("yMax")),
                    w.text or "",
                )
                for w in page.findall(f"{ns}word")
            ]
        )

    out: list[Widget] = []
    reader = PdfReader(pdf)
    for pnum, page in enumerate(reader.pages, 1):
        page_h = float(page.mediabox.top)
        words = pages_words[pnum - 1] if pnum <= len(pages_words) else []
        for a in page.get("/Annots") or []:
            o = a.get_object()
            if o.get("/Subtype") != "/Widget":
                continue
            x0, y0, x1, y1 = (float(v) for v in o.get("/Rect"))
            cy = page_h - (y0 + y1) / 2
            same = sorted(
                (w for w in words if abs((w[1] + w[3]) / 2 - cy) < 6 and w[2] <= x0 + 2),
                key=lambda w: w[0],
            )
            above = sorted(
                (w for w in words if cy - 22 < (w[1] + w[3]) / 2 < cy - 6 and w[0] < x1),
                key=lambda w: w[0],
            )
            out.append(
                Widget(
                    page=pnum,
                    x=x0,
                    y_top=page_h - y1,
                    h=y1 - y0,
                    is_text=str(o.get("/FT", "")) == "/Tx",
                    label=" ".join(w[4] for w in same[-8:]),
                    context=" ".join(w[4] for w in above[-9:]),
                )
            )
    out.sort(key=lambda w: (w.page, w.y_top, w.x))
    return out


def build_fieldmap(pdf: Path) -> dict[str, dict[str, float | int | str]]:
    """Semantic name → stamp spec, derived from the contract's own AcroForm
    widget geometry plus the label text printed next to each widget.

    Keying on label text (not the generic "Zeile N" field names) is what
    makes ONE matcher work across all four documents, whose numbering and
    positions all differ. Every semantic below is asserted present — a
    future VDIV wording change fails the build instead of silently
    producing an offer with an unstamped slot.
    """
    widgets = _read_widgets(pdf)
    texts = [w for w in widgets if w.is_text]
    checks = [w for w in widgets if not w.is_text]

    def spec(w: Widget, *, size: float | None = None, dx: float = 2.0) -> dict:
        return {
            "page": w.page,
            "x": round(w.x + dx, 1),
            "y_top": round(w.y_top + 1.0, 1),
            "size": size if size is not None else round(min(9.0, w.h - 2.6), 1),
        }

    def one_text(pred, what: str) -> Widget:
        hits = [w for w in texts if pred(w)]
        if len(hits) != 1:
            raise SystemExit(f"{pdf.name}: expected exactly 1 match for {what}, got {len(hits)}")
        return hits[0]

    def checkbox_at(anchor: Widget, what: str) -> Widget:
        hits = [
            c
            for c in checks
            if c.page == anchor.page and abs(c.y_top - anchor.y_top) < 8 and c.x < anchor.x
        ]
        if not hits:
            raise SystemExit(f"{pdf.name}: no checkbox on the {what} line")
        return hits[0]

    # Page 1: parties + object. The party rules carry no label text, so
    # order-by-position identifies them: two Eigentümer rules, two
    # Verwalter rules, then the two Verwaltungsobjekt rules further down.
    # Deliberately type-agnostic: the Unternehmer PDFs mis-type one Objekt
    # rule as a checkbox — the height filter keeps real checkboxes (~9pt) out.
    page1_widgets = [w for w in widgets if w.page == 1]
    plain = [w for w in page1_widgets if not w.label and w.h > 15]
    if len(plain) < 6:
        raise SystemExit(f"{pdf.name}: expected ≥6 unlabeled rules on page 1, got {len(plain)}")

    m: dict[str, dict] = {
        "eigentuemer_1": spec(plain[0], size=9.0),
        "eigentuemer_2": spec(plain[1], size=9.0),
        "verwalter_1": spec(plain[2], size=9.0),
        "verwalter_2": spec(plain[3], size=9.0),
        "objekt_1": spec(plain[4], size=9.0),
        "objekt_2": spec(plain[5], size=9.0),
    }

    unbef = one_text(lambda w: "unbestimmte Zeit mit Wirkung ab" in w.label, "unbefristet ab")
    m["unbefristet_ab"] = spec(unbef)
    cb = checkbox_at(unbef, "unbefristet")
    m["unbefristet_check"] = spec(cb, size=cb.h - 1.0, dx=1.5)

    m["gv_inline"] = spec(one_text(lambda w: w.label.strip() == "von", "GV inline"))
    m["gv_netto"] = spec(one_text(lambda w: w.label.strip().endswith("Grundvergütung"), "GV netto"))
    # MV says "Umsatzsteuer", SEV says "Mehrwertsteuer" for the same slot.
    m["gv_ust"] = spec(
        one_text(lambda w: "Umsatzsteuer" in w.label or "Mehrwertsteuer" in w.label, "GV USt")
    )
    m["gv_gesamt"] = spec(one_text(lambda w: "Gesamt monatlich" in w.label, "GV gesamt"))
    # §5.5's percent slot stays EMPTY: WHV keeps the legacy +1 EUR/Einheit
    # escalator, stamped as a §13 Sonstige Vereinbarung instead (below).
    anchor = [w for w in texts if "SONSTIGE" in (w.label + w.context).upper() and w.h > 14]
    if not anchor:
        raise SystemExit(f"{pdf.name}: no Sonstige-Vereinbarungen anchor found")
    a = anchor[0]
    # The sibling rules share the anchor's page + x column right below it.
    sonstige = sorted(
        (
            w
            for w in texts
            if w.page == a.page and abs(w.x - a.x) < 3 and a.y_top <= w.y_top < a.y_top + 80
        ),
        key=lambda w: w.y_top,
    )
    if len(sonstige) < 2:
        raise SystemExit(
            f"{pdf.name}: expected ≥2 Sonstige-Vereinbarungen rules, got {len(sonstige)}"
        )
    m["sonstige_1"] = spec(sonstige[0], size=8.5)
    m["sonstige_2"] = spec(sonstige[1], size=8.5)
    m["rechnungslegung_monate"] = spec(
        one_text(lambda w: "innerhalb von" in w.label, "Rechnungslegung Monate")
    )

    # Fälligkeit b): first option is "am dritten Werktag", the NEXT checkbox
    # in reading order is the Entnahme-vom-Verwaltungskonto option WHV uses.
    faellig = [c for c in checks if "Fälligkeit" in c.context]
    if len(faellig) != 1:
        raise SystemExit(f"{pdf.name}: expected 1 Fälligkeit checkbox, got {len(faellig)}")
    idx = checks.index(faellig[0])
    if idx + 1 >= len(checks):
        raise SystemExit(f"{pdf.name}: no Entnahme checkbox after the Fälligkeit one")
    entnahme = checks[idx + 1]
    m["faelligkeit_entnahme_check"] = spec(entnahme, size=entnahme.h - 1.0, dx=1.5)

    # §6.1 first option: the Verwalter opens an offenes Fremdkonto in the
    # owner's name (the 2026 generation has no Treuhandkonto option; the
    # attached DKB form covers wirtschaftlich Berechtigte either way).
    konto = [c for c in checks if "6.1 Konto" in c.context]
    if len(konto) != 1:
        raise SystemExit(f"{pdf.name}: expected 1 Konto checkbox, got {len(konto)}")
    m["konto_fremdkonto_check"] = spec(konto[0], size=konto[0].h - 1.0, dx=1.5)

    return m


def flatten_contract(src: Path) -> bytes:
    """Bake AcroForm fields into the page content via Ghostscript."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as out:
        subprocess.run(
            [
                "gs",
                "-dBATCH",
                "-dNOPAUSE",
                "-dQUIET",
                "-sDEVICE=pdfwrite",
                "-dPreserveAnnots=false",
                f"-sOutputFile={out.name}",
                str(src),
            ],
            check=True,
        )
        data = Path(out.name).read_bytes()
    reader = PdfReader(BytesIO(data))
    if reader.get_fields():
        raise SystemExit(f"flatten failed — {src.name} still has form fields")
    if not (reader.pages[0].extract_text() or "").strip():
        raise SystemExit(f"flatten broke the text layer of {src.name}")
    return data


def dkb_verification_page() -> PdfReader:
    """The blanked, WHV-prefilled DKB Treuhandkonto page — reused from the
    committed (pre-2026) MV template rather than re-blanked from scratch."""
    legacy = ASSET_DIR / "mv_template.pdf"
    reader = PdfReader(legacy)
    return reader  # page index 8 (9th page) is the DKB form


def build(
    line: str, label: str, contract_pdf: Path, lv_xlsx: Path, out_name: str
) -> dict[str, dict]:
    fieldmap = build_fieldmap(contract_pdf)
    contract = flatten_contract(contract_pdf)

    # Bake the static Verwalter block in at build time; runtime only stamps
    # per-customer values. The two specs are consumed here and dropped from
    # the committed map.
    verwalter_stamps = [
        StampField(
            text=_WHV_NAME, align="left", **{k: v for k, v in fieldmap.pop("verwalter_1").items()}
        ),
        StampField(
            text=_WHV_ADDRESS,
            align="left",
            **{k: v for k, v in fieldmap.pop("verwalter_2").items()},
        ),
    ]
    contract = stamp_pdf(contract, verwalter_stamps)

    anlage = render_anlage(label, read_lv_rows(lv_xlsx))

    writer = PdfWriter()
    for page in PdfReader(BytesIO(contract)).pages:
        writer.add_page(page)
    for page in PdfReader(BytesIO(anlage)).pages:
        writer.add_page(page)
    writer.add_page(dkb_verification_page().pages[8])

    out = ASSET_DIR / out_name
    with out.open("wb") as fh:
        writer.write(fh)
    n = len(PdfReader(out).pages)
    print(f"{out_name}: {n} Seiten, {len(fieldmap)} Laufzeit-Felder")
    return fieldmap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mv-dir", required=True)
    ap.add_argument("--sev-dir", required=True)
    args = ap.parse_args()
    mv_dir = Path(args.mv_dir).expanduser()
    sev_dir = Path(args.sev_dir).expanduser()

    fieldmaps: dict[str, dict] = {}
    for line, label, src_dir, stem in [
        ("mv", "Mietverwaltung", mv_dir, "Verwaltervertrag_Mietverwaltung"),
        ("sev", "Sondereigentumsverwaltung (SEV)", sev_dir, "Verwaltervertrag_SEV"),
    ]:
        lv = next(src_dir.glob("Leistungsverzeichnis_*Kompaktfassung.xlsx"))
        for variant in ("Verbraucher", "Unternehmer"):
            key = f"{line}_{variant.lower()}"
            fieldmaps[key] = build(
                line,
                label,
                src_dir / f"{stem}_{variant}.pdf",
                lv,
                f"{key}_template.pdf",
            )

    with (ASSET_DIR / "fieldmaps.json").open("w") as fh:
        json.dump(fieldmaps, fh, indent=2, sort_keys=True, ensure_ascii=False)
    print(f"fieldmaps.json: {len(fieldmaps)} Karten")


if __name__ == "__main__":
    sys.exit(main())
