"""Dump every AcroForm widget of a VDIV contract with its nearest label text.

Aid for building the semantic field maps in build_offer_templates.py: for
each text/checkbox widget it prints the words on the same visual line to its
left (the label) plus the tail of the line above (context), so "Zeile 12"
can be identified as, say, the Umsatzsteuer amount without opening the PDF.

    .venv/bin/python scripts/dump_offer_fields.py <contract.pdf>
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from pypdf import PdfReader


def word_boxes(pdf: Path) -> dict[int, list[tuple[float, float, float, float, str]]]:
    """Per page: (xmin, ymin, xmax, ymax, text) in top-left origin, via
    pdftotext -bbox."""
    xml = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"], check=True, capture_output=True
    ).stdout
    root = ET.fromstring(xml)
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    pages: dict[int, list[tuple[float, float, float, float, str]]] = {}
    for pnum, page in enumerate(root.iter("{http://www.w3.org/1999/xhtml}page"), 1):
        words = []
        for w in page.findall("x:word", ns):
            words.append(
                (
                    float(w.get("xMin")),
                    float(w.get("yMin")),
                    float(w.get("xMax")),
                    float(w.get("yMax")),
                    w.text or "",
                )
            )
        pages[pnum] = words
    return pages


def main() -> None:
    pdf = Path(sys.argv[1]).expanduser()
    words = word_boxes(pdf)
    reader = PdfReader(pdf)
    for pnum, page in enumerate(reader.pages, 1):
        page_h = float(page.mediabox.top)
        for a in page.get("/Annots") or []:
            o = a.get_object()
            if o.get("/Subtype") != "/Widget":
                continue
            name = str(o.get("/T", "") or "?")
            ft = str(o.get("/FT", ""))
            x0, y0, x1, y1 = (float(v) for v in o.get("/Rect"))
            top = page_h - y1  # widget top edge, top-left origin
            cy = page_h - (y0 + y1) / 2  # widget line center
            same_line = [
                w for w in words.get(pnum, []) if abs((w[1] + w[3]) / 2 - cy) < 6 and w[2] <= x0 + 2
            ]
            same_line.sort(key=lambda w: w[0])
            label = " ".join(w[4] for w in same_line[-7:])
            above = [
                w for w in words.get(pnum, []) if cy - 22 < (w[1] + w[3]) / 2 < cy - 6 and w[0] < x1
            ]
            above.sort(key=lambda w: w[0])
            context = " ".join(w[4] for w in above[-8:])
            kind = "TXT" if ft == "/Tx" else "CHK"
            print(
                f"S.{pnum} {kind} {name[:24]:26} x={x0:5.1f} y_top={top:6.1f} "
                f"h={y1 - y0:4.1f} | {label[-60:]:<60} || {context[-55:]}"
            )


if __name__ == "__main__":
    main()
