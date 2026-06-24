"""Meter-reading photo storage on local disk.

Mirror of `app/integrations/storage/ticket_attachments.py` — same
`local-disk:<suffix>` convention, different directory + a tighter,
image-only allow-list (a Zählerstand photo is always a phone snap, never
an office doc). Bytes live at
`{meter_reading_photo_dir}/{reading_id}{suffix}`. Same Hetzner OS
migration plan as the other storage helpers; the swap is one file.
"""

import uuid
from pathlib import Path

from app.config import get_settings


class MeterPhotoStorageError(ValueError):
    """Raised when a meter-reading photo can't be persisted (bad type)."""


# Images only — the meter-reading capture flow is camera-first. HEIC/HEIF
# included because that's the iPhone default. We never execute the bytes;
# the cap + extension check are belt-and-braces.
_ALLOWED_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".gif",
    ".bmp",
}


def _safe_suffix(filename: str) -> str:
    """Lower-cased allow-listed extension, or raise. Path components are
    dropped (we only look at the suffix) so a hostile `../../x` filename
    can't traverse out."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise MeterPhotoStorageError(f"Nicht unterstütztes Bildformat: {suffix or '(keins)'}")
    return suffix


def photo_path(reading_id: uuid.UUID, suffix: str) -> Path:
    return Path(get_settings().meter_reading_photo_dir) / f"{reading_id}{suffix}"


def write_photo(reading_id: uuid.UUID, filename: str, data: bytes) -> tuple[Path, str]:
    """Persist raw bytes under settings.meter_reading_photo_dir.

    Returns (path, suffix). The suffix is the canonical lower-cased
    extension to stamp on `photo_storage_url` — callers should use this
    value, not re-derive it from the filename.
    """
    suffix = _safe_suffix(filename)
    base = Path(get_settings().meter_reading_photo_dir)
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{reading_id}{suffix}"
    out.write_bytes(data)
    return out, suffix


def delete_photo(reading_id: uuid.UUID, suffix: str) -> None:
    """Best-effort cleanup. No-op if the file is already gone."""
    path = photo_path(reading_id, suffix)
    if path.exists():
        path.unlink()
