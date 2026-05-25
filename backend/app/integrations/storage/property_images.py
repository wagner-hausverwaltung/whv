"""Property hero photo storage.

Mirrors the avatar pattern (PIL normalise → PNG → on-disk under
settings.property_image_dir) but with a bigger target box because these
photos sit at the top of a property page, not in a 32px nav badge.
"""

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import get_settings

_ALLOWED_INPUT_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}
_TARGET_SIZE = (1280, 960)


class PropertyImageError(ValueError):
    """Raised when the uploaded bytes can't be turned into a valid image."""


def _path_for(property_id: uuid.UUID) -> Path:
    settings = get_settings()
    return Path(settings.property_image_dir) / f"{property_id}.png"


def write_property_image(property_id: uuid.UUID, raw: bytes) -> str:
    """Persist a Verwalter-uploaded image as a normalised PNG and return
    the relative URL the SPA + `<img>` tag can fetch.

    Raises PropertyImageError on bad input. The directory is created on
    first write — no provisioning step needed.
    """
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        probe = Image.open(io.BytesIO(raw))  # verify() invalidates the stream
        if probe.format not in _ALLOWED_INPUT_FORMATS:
            raise PropertyImageError(f"Unsupported image format: {probe.format}")
    except (UnidentifiedImageError, OSError) as exc:
        raise PropertyImageError("Could not decode image") from exc

    # RGBA so transparent inputs (PNG) round-trip cleanly. JPEGs come in as
    # RGB; converting to RGBA is harmless.
    img: Image.Image = probe.convert("RGBA")
    img.thumbnail(_TARGET_SIZE, Image.Resampling.LANCZOS)

    settings = get_settings()
    base = Path(settings.property_image_dir)
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f"{property_id}.png"
    img.save(out_path, "PNG", optimize=True)

    # Cache-bust query so the browser re-fetches when the photo changes.
    mtime = int(out_path.stat().st_mtime)
    return f"/admin/property-images/{property_id}.png?v={mtime}"


def delete_property_image(property_id: uuid.UUID) -> None:
    path = _path_for(property_id)
    if path.exists():
        path.unlink()
