"""Tests for RAG PDF extraction (ADR-0013 §3).

Born-digital extraction runs for real (reportlab → pypdf, no binaries).
The OCR fallback is exercised with pdf2image / pytesseract mocked so the
suite stays deterministic and green in CI without Tesseract installed.
"""

from io import BytesIO

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.rag.extraction import ExtractionError, extract_pdf


def _make_pdf(page_texts: list[str]) -> bytes:
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    for text in page_texts:
        pdf.drawString(72, 750, text)
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


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

    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda *a, **k: ["IMG0"])
    monkeypatch.setattr("pytesseract.image_to_string", fake_ocr)

    result = extract_pdf(pdf, ocr_lang="deu")
    assert result.ocr_engine == "tesseract-deu"
    assert result.pages == ["OCR<IMG0|deu>"]


def test_extract_mixed_only_ocrs_scanned_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(["Lange digitale Seite mit Text", "y"])  # page 2 is a scan
    seen: list[object] = []

    def fake_ocr(img: object, lang: str | None = None) -> str:
        seen.append(img)
        return "Gescannte Seite zwei"

    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda *a, **k: ["IMG0", "IMG1"])
    monkeypatch.setattr("pytesseract.image_to_string", fake_ocr)

    result = extract_pdf(pdf)
    assert result.ocr_engine == "mixed-tesseract-deu"
    assert "digitale" in result.pages[0]
    assert result.pages[1] == "Gescannte Seite zwei"
    assert seen == ["IMG1"]  # only the scanned page hit OCR
