"""Ticket attachment storage on local disk.

Mirror of `app/integrations/storage/documents.py` — same conventions,
different directory + caller scope. The split is deliberate so the two
surfaces can evolve their allow-lists independently (a Verwalter PDF
library is conservative; ticket attachments accept photos, screenshots,
inline images that came in via email, etc.).

Storage URL convention: `local-disk:<suffix>` is stamped on
`ticket_message_attachments.storage_url`. Bytes live at
`{ticket_attachment_dir}/{attachment_id}{suffix}`. Same Hetzner OS
migration plan as the other storage helpers; the swap is one file.
"""

import uuid
from pathlib import Path

from app.config import get_settings


class TicketAttachmentStorageError(ValueError):
    """Raised when an upload can't be persisted (bad extension etc.)."""


# Broader allow-list than documents — ticket attachments often arrive
# as inline images from an Outlook reply, phone snapshots, or office
# files contractors send back. Executables intentionally absent (no
# .exe / .bat / .sh / .scr) so a careless click on the download link
# can't launch arbitrary code. We never execute the bytes; this is
# just belt-and-braces.
_ALLOWED_SUFFIXES = {
    # PDFs + office docs (mirror of documents.py).
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".odt",
    ".ods",
    ".txt",
    ".csv",
    # Images — by far the most common attachment, both phone snapshots
    # and inline Outlook signatures.
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
    # Archives that arrive from contractors.
    ".zip",
    # Plaintext / structured-data formats we've seen real customers send:
    # JSON exports, XML invoices (XRechnung), raw email forwards, server
    # logs, YAML configs. Still no executables — we never run these
    # bytes; this is belt-and-braces against a careless click on the
    # download link.
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".eml",
}


def _safe_suffix(filename: str) -> str:
    """Lower-cased allow-listed extension, or raise. Path components in
    the filename are dropped (we only look at the suffix) so a hostile
    `../../etc/passwd` upload can't traverse out."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise TicketAttachmentStorageError(f"Unsupported file type: {suffix or '(none)'}")
    return suffix


def attachment_path(attachment_id: uuid.UUID, suffix: str) -> Path:
    return Path(get_settings().ticket_attachment_dir) / f"{attachment_id}{suffix}"


def write_attachment(attachment_id: uuid.UUID, filename: str, data: bytes) -> tuple[Path, str]:
    """Persist raw bytes under settings.ticket_attachment_dir.

    Returns (path, suffix). The suffix is the canonical lower-cased
    extension we'll stamp on storage_url — callers should always use
    this value, not derive it from the filename a second time.
    """
    suffix = _safe_suffix(filename)
    base = Path(get_settings().ticket_attachment_dir)
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{attachment_id}{suffix}"
    out.write_bytes(data)
    return out, suffix


def delete_attachment(attachment_id: uuid.UUID, suffix: str) -> None:
    """Best-effort cleanup after a hard-delete. No-op if the file is
    already gone — useful when an upload half-succeeded."""
    path = attachment_path(attachment_id, suffix)
    if path.exists():
        path.unlink()
