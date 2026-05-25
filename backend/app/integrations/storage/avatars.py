"""Avatar storage + image processing.

User-uploaded profile pictures are normalised by Pillow (PNG, fit in a
256x256 square via thumbnail) and written to settings.avatar_dir keyed by
user id. The static-files mount at /me/avatars/ serves them publicly —
user IDs are UUIDv7, so the URLs are unguessable, and there's no
sensitivity attached to an avatar image.
"""

import io
import logging
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Register pillow-heif's HEIC/HEIF opener with Pillow so .heic/.heif
# uploads from iPhone (the iOS 11+ default photo format) decode through
# Image.open() like any other format. Import-time call is idempotent
# but cheap. We tolerate the import failing — if pillow-heif isn't
# installed the rest of the avatar pipeline still works for the legacy
# JPEG/PNG/WEBP set, the user just gets a clear "unsupported format"
# error on a HEIC upload instead of a silent decode failure.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - only hit on a partial install
    logger.warning("pillow_heif not installed; HEIC/HEIF avatars won't decode")

# Pillow recognises many input formats; we restrict to the common web set
# (now including HEIF for iPhone) so a corrupt RIFF chunk or exotic
# format can't slip through.
_ALLOWED_INPUT_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP", "HEIF"}
_TARGET_SIZE = (256, 256)


class AvatarError(ValueError):
    """Raised when the uploaded bytes can't be turned into a valid avatar."""


def _avatar_path(user_id: uuid.UUID) -> Path:
    settings = get_settings()
    return Path(settings.avatar_dir) / f"{user_id}.png"


def write_avatar(user_id: uuid.UUID, raw: bytes) -> str:
    """Persist a user-uploaded image as a normalised PNG and return the
    relative URL the SPA + `<img>` tag can fetch.

    Raises AvatarError on bad input (unrecognised format, decoding failure).
    The directory is created on first write — no provisioning step needed.
    """
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        # PIL invalidates the stream after verify(); re-open for processing.
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in _ALLOWED_INPUT_FORMATS:
            raise AvatarError(f"Unsupported image format: {probe.format}")
    except (UnidentifiedImageError, OSError) as exc:
        raise AvatarError("Could not decode image") from exc

    # Convert to RGBA so transparent inputs (PNG) and opaque (JPEG) both
    # round-trip cleanly through PNG output without weird palette artefacts.
    img: Image.Image = probe.convert("RGBA")
    img.thumbnail(_TARGET_SIZE, Image.Resampling.LANCZOS)

    settings = get_settings()
    base = Path(settings.avatar_dir)
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f"{user_id}.png"
    img.save(out_path, "PNG", optimize=True)

    # Cache-bust on every upload so the browser re-fetches when a user
    # changes their photo. The file path doesn't change — only the query.
    # Using mtime keeps it deterministic so two requests in the same second
    # still get the same URL.
    mtime = int(out_path.stat().st_mtime)
    return f"/me/avatars/{user_id}.png?v={mtime}"


def delete_avatar(user_id: uuid.UUID) -> None:
    """Remove the on-disk PNG. No-op if the file doesn't exist yet."""
    path = _avatar_path(user_id)
    if path.exists():
        path.unlink()
