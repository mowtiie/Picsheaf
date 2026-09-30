"""Supported input image formats.

This is the single place that knows which extensions/mime types the app
accepts — window.py's file picker filter and drag-and-drop validation
both read from SUPPORTED_FORMATS rather than hardcoding a format list.

Registering the HEIF/HEIC Pillow plugin (pillow-heif) also happens here,
once, as an import-time side effect. Both conversion.py and thumbnails.py
import this module (even though most of them don't use its exports
directly) so that plain PIL.Image.open() calls transparently gain HEIC
support without each caller needing to know pillow-heif exists.
"""
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

# extension -> mime type. Tier 1 (JPEG/PNG/BMP/TIFF/GIF/WebP) needs no
# extra dependency beyond Pillow + ImageMagick, both already required.
SUPPORTED_FORMATS = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
}

# Tier 2: only available when pillow-heif is installed.
if HEIF_SUPPORTED:
    SUPPORTED_FORMATS[".heic"] = "image/heic"
    SUPPORTED_FORMATS[".heif"] = "image/heif"

SUPPORTED_EXTENSIONS = frozenset(SUPPORTED_FORMATS.keys())


def is_supported(path: str) -> bool:
    """Case-insensitive extension check."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS)
