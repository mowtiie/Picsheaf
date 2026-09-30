"""Picsheaf — convert a set of images into a single PDF.

This module deliberately imports nothing beyond the standard library.
web2pdf_manager.sh reads __version__ directly (`python3 -c "import
picsheaf; print(picsheaf.__version__)"`) to stamp the AppImage filename
and AppStream metadata, so this file must stay importable even on a
system that doesn't have PyGObject/GTK installed yet (e.g. before
`./web2pdf_manager.sh setup` has run).
"""

__version__ = "1.0.0"
APP_ID = "io.github.mowtiie.Picsheaf"
