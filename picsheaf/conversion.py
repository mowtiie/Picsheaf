"""Pure image -> PDF conversion pipeline.

No GTK/GLib dependency by design: this module can be imported, called,
and unit tested with nothing but Pillow and img2pdf installed, and is a
natural place to hang a future CLI (`picsheaf-cli in1.webp in2.webp -o
out.pdf`) without touching any UI code.
"""
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import img2pdf
from PIL import Image

# Import for its side effect: registers the HEIF/HEIC Pillow plugin (when
# installed) before any Image.open() call below runs. See image_formats.py.
from picsheaf import image_formats  # noqa: F401


@dataclass
class ConversionResult:
    success: bool
    message: str
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


def convert_images_to_pdf(
    input_files: List[str],
    output_pdf: str,
    quality: int,
    dpi: int,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ConversionResult:
    """Convert a list of image files (in the given order) into a single PDF.

    progress_cb(done, total) is called after each file is processed, if
    given. should_cancel() is polled before each file; if it returns
    True, the batch stops early, no PDF is written, and the result has
    cancelled=True. Files that fail to convert are skipped (reported in
    result.skipped) rather than aborting the whole batch.
    """
    temp_jpgs = []
    total = len(input_files)
    skipped: List[Tuple[str, str]] = []

    try:
        temp_dir = tempfile.mkdtemp()
        for idx, webp_path in enumerate(input_files):
            if should_cancel is not None and should_cancel():
                return ConversionResult(success=False, message="Conversion cancelled.", cancelled=True)

            jpg_path = os.path.join(temp_dir, f"page_{idx:04d}.jpg")
            converted, reason = _convert_one(webp_path, jpg_path, quality)
            if converted:
                temp_jpgs.append(jpg_path)
            else:
                skipped.append((os.path.basename(webp_path), reason))

            if progress_cb is not None:
                progress_cb(idx + 1, total)

        if not temp_jpgs:
            return ConversionResult(success=False, message="All files failed to convert.", skipped=skipped)

        # layout_fun pins the page size to the chosen DPI rather than
        # whatever DPI metadata (if any) happened to be in the source.
        layout_fun = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
        with open(output_pdf, "wb") as f:
            f.write(img2pdf.convert(temp_jpgs, layout_fun=layout_fun))

        message = f"Successfully created {os.path.basename(output_pdf)}!"
        if skipped:
            message += f" ({len(skipped)} file(s) skipped — see details)"
        return ConversionResult(success=True, message=message, skipped=skipped)
    except Exception as err:
        return ConversionResult(success=False, message=f"Error: {str(err)}")
    finally:
        for f in temp_jpgs:
            if os.path.exists(f):
                os.remove(f)


def _convert_one(webp_path: str, jpg_path: str, quality: int) -> Tuple[bool, str]:
    """Try ImageMagick first, then Pillow as a fallback.
    Returns (converted, reason) — reason is only meaningful when
    converted is False, and is the most useful error text available."""
    magick_reason = ""
    try:
        subprocess.run(
            ["convert", "-quality", str(quality), webp_path, jpg_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return True, ""
    except Exception as magick_err:
        stderr = getattr(magick_err, "stderr", b"") or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="ignore")
        magick_reason = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        try:
            with Image.open(webp_path) as img:
                img.convert("RGB").save(jpg_path, "JPEG", quality=quality)
            return True, ""
        except Exception as pillow_err:
            reason = str(pillow_err) or magick_reason or "Unknown conversion error"
            return False, reason
