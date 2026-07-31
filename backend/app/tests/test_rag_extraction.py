"""Tests for RAG PDF extraction (ADR-0013 §3).

Born-digital extraction runs for real (reportlab → pypdf, no binaries).
The OCR fallback is exercised with pdf2image / pytesseract mocked so the
suite stays deterministic and green in CI without Tesseract installed.
"""

from io import BytesIO

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.rag.extraction import _OCR_MAX_PAGES_PER_PASS, ExtractionError, extract_pdf


def _make_pdf(page_texts: list[str]) -> bytes:
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    for text in page_texts:
        pdf.drawString(72, 750, text)
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


class _FakeImage:
    """Stands in for a PIL image: identifies its page and tracks close()."""

    def __init__(self, page: int) -> None:
        self.page = page
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def __repr__(self) -> str:
        return f"IMG{self.page}"


def _fake_convert(calls: list[tuple[int, int]], produced: list[_FakeImage]) -> object:
    """Fake ``convert_from_bytes`` that honours poppler's 1-based inclusive
    ``first_page``/``last_page``, so windowed rasterisation is exercised for
    real rather than papered over by a mock that returns every page."""

    def convert(
        _pdf_bytes: bytes,
        *,
        dpi: int = 200,
        first_page: int = 1,
        last_page: int | None = None,
    ) -> list[_FakeImage]:
        last = last_page if last_page is not None else first_page
        calls.append((first_page, last))
        images = [_FakeImage(page) for page in range(first_page, last + 1)]
        produced.extend(images)
        return images

    return convert


def test_extract_born_digital_reads_text_layer() -> None:
    pdf = _make_pdf(["Rechnung Mustermann GmbH 2025", "Seite zwei Inhalt hier"])
    result = extract_pdf(pdf)
    assert result.page_count == 2
    assert result.ocr_engine == "pdf-text-layer"
    assert "Rechnung" in result.pages[0]
    assert "zwei" in result.pages[1]


def test_extract_invalid_bytes_raises() -> None:
    with pytest.raises(ExtractionError):
        extract_pdf(b"definitely not a pdf")


def test_extract_scanned_falls_back_to_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(["x"])  # < _MIN_TEXT_LAYER_CHARS → treated as a scan

    def fake_ocr(img: object, lang: str | None = None) -> str:
        return f"OCR<{img}|{lang}>"

    monkeypatch.setattr("pdf2image.convert_from_bytes", _fake_convert([], []))
    monkeypatch.setattr("pytesseract.image_to_string", fake_ocr)

    result = extract_pdf(pdf, ocr_lang="deu")
    assert result.ocr_engine == "tesseract-deu"
    assert result.pages == ["OCR<IMG1|deu>"]


def test_extract_mixed_only_ocrs_scanned_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(["Lange digitale Seite mit Text", "y"])  # page 2 is a scan
    seen: list[object] = []
    calls: list[tuple[int, int]] = []

    def fake_ocr(img: object, lang: str | None = None) -> str:
        seen.append(repr(img))
        return "Gescannte Seite zwei"

    monkeypatch.setattr("pdf2image.convert_from_bytes", _fake_convert(calls, []))
    monkeypatch.setattr("pytesseract.image_to_string", fake_ocr)

    result = extract_pdf(pdf)
    assert result.ocr_engine == "mixed-tesseract-deu"
    assert "digitale" in result.pages[0]
    assert result.pages[1] == "Gescannte Seite zwei"
    assert seen == ["IMG2"]  # only the scanned page hit OCR
    assert calls == [(2, 2)]  # and only that page was rasterised


def test_ocr_rasterises_in_bounded_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long scan must never be rasterised in one pass — that is what
    exhausted the prod worker's memory and OOM-killed it nightly."""
    page_count = _OCR_MAX_PAGES_PER_PASS * 3 + 1
    pdf = _make_pdf(["x"] * page_count)  # every page is a "scan"
    calls: list[tuple[int, int]] = []
    produced: list[_FakeImage] = []

    monkeypatch.setattr("pdf2image.convert_from_bytes", _fake_convert(calls, produced))
    monkeypatch.setattr("pytesseract.image_to_string", lambda img, lang=None: repr(img))

    result = extract_pdf(pdf)

    assert result.page_count == page_count
    assert result.pages == [f"IMG{page}" for page in range(1, page_count + 1)]
    # Several bounded passes, none wider than the cap.
    assert len(calls) == 4
    assert all(last - first + 1 <= _OCR_MAX_PAGES_PER_PASS for first, last in calls)
    # Every page rasterised exactly once, and all bitmaps released.
    assert sorted(img.page for img in produced) == list(range(1, page_count + 1))
    assert all(img.closed for img in produced)


def test_ocr_window_spans_are_capped_for_scattered_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed documents: a few scattered scan pages far apart must not cause a
    single pass that spans (and rasterises) the whole document."""
    pages = ["Lange digitale Seite mit Text"] * 40
    pages[0] = "x"
    pages[20] = "y"
    pages[39] = "z"
    calls: list[tuple[int, int]] = []

    monkeypatch.setattr("pdf2image.convert_from_bytes", _fake_convert(calls, []))
    monkeypatch.setattr("pytesseract.image_to_string", lambda img, lang=None: repr(img))

    result = extract_pdf(_make_pdf(pages))

    assert calls == [(1, 1), (21, 21), (40, 40)]
    # And the OCR text must land on the pages it came from — a wrong-page
    # write is the silent failure this whole change risks.
    assert result.pages[0] == "IMG1"
    assert result.pages[20] == "IMG21"
    assert result.pages[39] == "IMG40"
    # Digital pages keep their text layer untouched.
    assert "digitale" in result.pages[1]
    assert "digitale" in result.pages[38]
