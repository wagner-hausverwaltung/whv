"""ETV agenda-item attachment storage on local disk.

Same convention as `app/integrations/storage/announcements.py` —
`storage_url` stamps `local-disk:<suffix>`; bytes live at
`{etv_attachment_dir}/{attachment_id}{suffix}`. Hetzner Object
Storage migration (REQUIREMENTS.md §1.4d iter 2) replaces this with
bucket URLs without changing the helper's surface.

Allow-list mirrors the announcement helper — owners attach the same
types of things (PDFs, photos, the occasional spreadsheet) as
context for a Tagesordnungspunkt.
"""

import uuid
from pathlib import Path

from app.config import get_settings


class EtvAttachmentStorageError(ValueError):
    """Raised when an upload can't be persisted (bad extension etc.)."""


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
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
    ".zip",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".eml",
}


def _safe_suffix(filename: str) -> str:
    """Lower-cased allow-listed extension, or raise. Path components in
    the filename are dropped — a `../../etc/passwd` upload can't
    traverse out of the storage dir."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise EtvAttachmentStorageError(f"Unsupported file type: {suffix or '(none)'}")
    return suffix


def attachment_path(attachment_id: uuid.UUID, suffix: str) -> Path:
    return Path(get_settings().etv_attachment_dir) / f"{attachment_id}{suffix}"


def write_attachment(attachment_id: uuid.UUID, filename: str, data: bytes) -> tuple[Path, str]:
    """Persist raw bytes under settings.etv_attachment_dir.

    Returns (path, suffix). The suffix is the canonical lower-cased
    extension we'll stamp on storage_url — callers should always use
    this value, not derive it from the filename again.
    """
    suffix = _safe_suffix(filename)
    base = Path(get_settings().etv_attachment_dir)
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{attachment_id}{suffix}"
    out.write_bytes(data)
    return out, suffix


def delete_attachment(attachment_id: uuid.UUID, suffix: str) -> None:
    """Best-effort cleanup. No-op if the file is already gone."""
    path = attachment_path(attachment_id, suffix)
    if path.exists():
        path.unlink()
