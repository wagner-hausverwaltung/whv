"""Document storage on local disk.

Verwalter-uploaded property documents (PDFs, scanned protocols, etc.)
live under settings.document_dir. Unlike avatars and property images
we don't normalise — PDFs go through byte-for-byte, with the original
extension preserved on disk so the FileResponse can hand the browser
the right media type without an extra round-trip.

Why not a StaticFiles mount like avatars + property-images? Documents
carry a visibility scope (PRIVATE / OWNERS / TENANTS / …) — even if
UUIDv7 IDs are unguessable, leaking the URL of a PRIVATE protocol
would still hand the file to anyone. Downloads go through an
authenticated endpoint that re-checks the scope every time.

Same Hetzner-OS migration plan as resolution PDFs (§1.4d iter 2 in
REQUIREMENTS.md). The storage helper isolates the disk-vs-bucket
detail so swapping later is a one-file change.
"""

import uuid
from pathlib import Path

from app.config import get_settings


class DocumentStorageError(ValueError):
    """Raised when an upload can't be persisted (bad extension, etc.)."""


# Allow-list of file extensions we'll persist. PDF is the main format
# (Jahresabrechnung, Protokoll, Hausordnung, …); office docs in case a
# Verwalter prefers to upload the .docx source alongside the PDF.
_ALLOWED_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".odt",
    ".ods",
    ".txt",
    ".csv",
}


def _safe_suffix(filename: str) -> str:
    """Return the lower-cased extension if it's in the allow-list, else
    raise. Strips path components so an attacker can't inject `../`."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise DocumentStorageError(f"Unsupported file type: {suffix or '(none)'}")
    return suffix


def document_path(document_id: uuid.UUID, suffix: str) -> Path:
    """Absolute filesystem path for a document. Suffix should be one of
    `_ALLOWED_SUFFIXES` (including the leading dot)."""
    return Path(get_settings().document_dir) / f"{document_id}{suffix}"


def write_document(document_id: uuid.UUID, filename: str, data: bytes) -> tuple[Path, str]:
    """Persist raw upload bytes under settings.document_dir.

    Returns (path, suffix). Suffix is also returned so callers can store
    it on the Document row (mime_type already covers it, but the suffix
    lets us reconstruct the path without parsing MIME types again).
    """
    suffix = _safe_suffix(filename)
    base = Path(get_settings().document_dir)
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{document_id}{suffix}"
    out.write_bytes(data)
    return out, suffix


def delete_document(document_id: uuid.UUID, suffix: str) -> None:
    """Remove the file from disk. No-op if it doesn't exist — callers
    treat this as best-effort cleanup after a DB soft-delete."""
    path = document_path(document_id, suffix)
    if path.exists():
        path.unlink()
