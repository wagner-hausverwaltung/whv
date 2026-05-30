"""PDF text extraction for RAG ingestion (ADR-0013 §3).

Born-digital PDFs → read the text layer with pypdf (fast, no OCR). Pages
with little/no text layer (scans) → rasterise with pdf2image (poppler) and
OCR with Tesseract `deu` via pytesseract. The OCR toolchain lives in the
worker Docker image; pdf2image / pytesseract are imported lazily so this
module — and the born-digital path — loads fine without the binaries.

OCR text feeds SEMANTIC search only. Figures + dates come from Impower's
structured fields, never from OCR (ADR-0013 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

# Below this many characters a page's text layer is treated as absent
# (the page is a scan) and routed to OCR.
_MIN_TEXT_LAYER_CHARS = 20
# Rasterisation DPI for OCR — 200 balances accuracy vs. speed/memory on
# A4 Abrechnungen. Bump if Tesseract under-reads small print.
_OCR_DPI = 200


class ExtractionError(RuntimeError):
    """Raised when a document's bytes can't be parsed as a PDF."""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    pages: list[str]
    page_count: int
    # "pdf-text-layer" | "tesseract-<lang>" | "mixed-tesseract-<lang>"
    ocr_engine: str


def extract_pdf(pdf_bytes: bytes, *, ocr_lang: str = "deu") -> ExtractionResult:
    """Extract per-page text from a PDF: read the text layer where present,
    OCR pages that lack one. Returns one string per page, in order."""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception as exc:  # pypdf raises assorted errors on bad input
        raise ExtractionError(f"could not read PDF: {exc}") from exc

    pages: list[str] = []
    needs_ocr: list[int] = []
    for index, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        pages.append(text)
        if len(text) < _MIN_TEXT_LAYER_CHARS:
            needs_ocr.append(index)

    if needs_ocr:
        _ocr_pages_in_place(pdf_bytes, pages, needs_ocr, ocr_lang)

    if not needs_ocr:
        engine = "pdf-text-layer"
    elif len(needs_ocr) == len(pages):
        engine = f"tesseract-{ocr_lang}"
    else:
        engine = f"mixed-tesseract-{ocr_lang}"
    return ExtractionResult(pages=pages, page_count=len(pages), ocr_engine=engine)


def _ocr_pages_in_place(
    pdf_bytes: bytes, pages: list[str], indices: list[int], ocr_lang: str
) -> None:
    """OCR the given page indices, writing results back into ``pages``.

    Rasterises the whole PDF once (one poppler pass) and OCRs only the
    flagged pages. Scanned WHV documents are typically scans cover-to-cover,
    so rasterising every page is the common case anyway; the extra raster of
    a stray digital page in a mixed doc is cheap (no OCR is run on it).
    Lazy-imports keep the binaries off the import path until a scan is hit.
    """
    from pdf2image import convert_from_bytes
    from pytesseract import image_to_string

    images = convert_from_bytes(pdf_bytes, dpi=_OCR_DPI)
    for index in indices:
        if index < len(images):
            pages[index] = (image_to_string(images[index], lang=ocr_lang) or "").strip()
