"""Synthesised German metadata header for RAG ingestion (ADR-0013 §3).

Before chunking, we prepend a compact German metadata line to a
document's text so semantic search hits even on poor scans, e.g.::

    Rechnung · Mustermann GmbH · 4.812,00 € · 2025-03-14 · Schmidener Str. 32

The figures (`amount`, `issued_date`) come from Impower's STRUCTURED
fields, never from OCR — they are authoritative and any answer must cite
them rather than a number read off a scanned table.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.document import DocumentKind

_KIND_LABELS: dict[DocumentKind, str] = {
    DocumentKind.JAHRESABRECHNUNG: "Jahresabrechnung",
    DocumentKind.WIRTSCHAFTSPLAN: "Wirtschaftsplan",
    DocumentKind.PROTOKOLL: "Protokoll",
    DocumentKind.VERTRAG: "Vertrag",
    DocumentKind.RECHNUNG: "Rechnung",
    DocumentKind.UMLAUFBESCHLUSS: "Umlaufbeschluss",
    DocumentKind.HAUSORDNUNG: "Hausordnung",
    DocumentKind.SIGNATUR: "Signiertes Dokument",
    DocumentKind.SONSTIGES: "Dokument",
}


def format_eur(amount: Decimal) -> str:
    """Format a Decimal as a German EUR string: ``4.812,00 €`` (dot
    thousands separator, comma decimal)."""
    # Python's grouping uses ',' thousands + '.' decimal; swap to German
    # via a placeholder so the two separators don't clobber each other.
    formatted = f"{amount:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{formatted} €"


def build_metadata_header(
    *,
    kind: DocumentKind,
    name: str | None = None,
    contact_name: str | None = None,
    amount: Decimal | None = None,
    issued_date: date | None = None,
    property_label: str | None = None,
) -> str:
    """Build the ` · `-joined German metadata line. Falsy/None parts are
    dropped, so a bare invoice with only a kind still yields a clean line.
    """
    parts: list[str] = [_KIND_LABELS.get(kind, "Dokument")]
    if contact_name:
        parts.append(contact_name)
    if amount is not None:
        parts.append(format_eur(amount))
    if issued_date is not None:
        parts.append(issued_date.isoformat())
    if property_label:
        parts.append(property_label)
    if name:
        parts.append(name)
    return " · ".join(parts)
