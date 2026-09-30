"""Thumbnail generation for queued image files.

Pillow only — no GdkPixbuf/GTK dependency, so this is testable without a
display. Callers in the UI layer wrap the returned PNG bytes in a
GdkPixbuf themselves; that's presentation, not generation.
"""
import io

from PIL import Image

# Import for its side effect: registers the HEIF/HEIC Pillow plugin (when
# installed) before any Image.open() call below runs. See image_formats.py.
from picsheaf import image_formats  # noqa: F401


def generate_thumbnails_png_bytes(path: str, sizes) -> dict:
    """Return {size: png_bytes} for each requested size, decoding the
    source image only once. Raises on failure — callers decide how to
    handle that (e.g. leave the row's thumbnail blank)."""
    results = {}
    with Image.open(path) as im:
        im = im.convert("RGB")
        for size in sizes:
            thumb = im.copy()
            thumb.thumbnail((size, size))
            buf = io.BytesIO()
            thumb.save(buf, format="PNG")
            results[size] = buf.getvalue()
    return results


def generate_thumbnail_png_bytes(path: str, size: int) -> bytes:
    """Single-size convenience wrapper around generate_thumbnails_png_bytes."""
    return generate_thumbnails_png_bytes(path, [size])[size]

