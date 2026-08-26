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

import logging
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Below this many characters a page's text layer is treated as absent
# (the page is a scan) and routed to OCR.
_MIN_TEXT_LAYER_CHARS = 20
# Rasterisation DPI for OCR — 200 balances accuracy vs. speed/memory on
# A4 Abrechnungen. Bump if Tesseract under-reads small print.
_OCR_DPI = 200
# Max pages poppler may rasterise per pass. At 200 dpi an A4 page is
# ~1654x2339 px RGB ≈ 11.6 MB of uncompressed bitmap, and pdf2image +
# pytesseract each keep their own temp copy on top of that. Rasterising a
# whole document at once therefore scales peak memory with page count: the
# largest scans in the corpus are 74 pages, and two of those in flight
# (--concurrency=2) drove the worker to ~2.3-2.6 GB RSS and OOM-killed it 35x
# a night on the 3.8 GB prod box (no swap), taking the API down with it.
# Windowing caps the bitmaps at ~90 MB regardless of document length.
_OCR_MAX_PAGES_PER_PASS = 8


# Characters Postgres' text type cannot store (NUL) or that carry no meaning
# for search — stripped from every extracted page. A single 0x00 anywhere in a
# PDF's text layer (broken CID font maps produce them) otherwise aborts the
# whole INSERT with CharacterNotInRepertoireError, the task retries three times
# re-embedding the document each round, and the document silently never lands
# in the index. Tabs/newlines survive; they carry layout.
_DISALLOWED = {c: None for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}
_DISALLOWED[0x7F] = None


def scrub_text(text: str) -> str:
    """Strip control characters Postgres rejects or that add no signal, and
    drop unpaired surrogates (pypdf emits them for damaged encodings) so the
    result always encodes as UTF-8."""
    cleaned = text.translate(_DISALLOWED)
    # Surrogates survive in Python strs but blow up on encode; the round-trip
    # below is the cheapest way to drop exactly those code points.
    return cleaned.encode("utf-8", "ignore").decode("utf-8", "ignore")


def looks_like_pdf(data: bytes) -> bool:
    """Cheap magic-byte check. Impower serves e-invoices as raw ZUGFeRD/
    XRechnung XML under the same /documents/{id}/download endpoint; feeding
    those to pypdf only ever produces "Stream has ended unexpectedly". The
    figures and dates of an invoice come from Impower's structured fields
    anyway (ADR-0013 §3), so XML carries nothing for semantic search."""
    return data[:5] == b"%PDF-"


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
            text = scrub_text(page.extract_text() or "").strip()
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

    Rasterises in bounded windows of at most ``_OCR_MAX_PAGES_PER_PASS``
    pages, OCRs each window, then drops the bitmaps before the next pass.
    Peak memory is therefore a function of the window, not of the document —
    a one-pass raster of the whole PDF is what OOM-killed the prod worker.
    Lazy-imports keep the binaries off the import path until a scan is hit.
    """
    from pdf2image import convert_from_bytes
    from pytesseract import image_to_string

    for window in _raster_windows(indices, _OCR_MAX_PAGES_PER_PASS):
        # poppler page numbers are 1-based and the range is inclusive.
        first = window[0]
        images = convert_from_bytes(
            pdf_bytes, dpi=_OCR_DPI, first_page=first + 1, last_page=window[-1] + 1
        )
        expected = window[-1] - first + 1
        if len(images) < expected:
            # Those pages keep their (empty) text layer and drop out of
            # semantic search with no other trace — say so rather than
            # returning a quietly incomplete document.
            logger.warning(
                "OCR raster short: pages %d-%d returned %d of %d images",
                first + 1,
                window[-1] + 1,
                len(images),
                expected,
            )
        try:
            for index in window:
                offset = index - first
                # Lower bound matters: a negative offset would silently index
                # from the END of the list and write OCR text onto the wrong
                # page. Unreachable while indices arrive ascending, but the
                # failure mode is silent corruption, so guard it.
                if 0 <= offset < len(images):
                    text = scrub_text(image_to_string(images[offset], lang=ocr_lang) or "")
                    pages[index] = text.strip()
        finally:
            # Drop the bitmaps before rasterising the next window. Popping
            # rather than iterating avoids leaving a loop variable bound to
            # the window's last page while the next window rasterises.
            while images:
                images.pop().close()
            del images


def _raster_windows(indices: list[int], max_pages: int) -> list[list[int]]:
    """Group page indices into windows that each span at most ``max_pages``
    pages. Bounding the *span* (not just the count) matters for mixed
    documents, where a few scattered scan pages could otherwise span — and
    rasterise — the whole document in one pass."""
    windows: list[list[int]] = []
    current: list[int] = []
    for index in indices:
        if current and index - current[0] + 1 > max_pages:
            windows.append(current)
            current = []
        current.append(index)
    if current:
        windows.append(current)
    return windows
