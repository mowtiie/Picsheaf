# Picsheaf

A native GTK4 / Libadwaita desktop app for Linux that converts one or more
images into a single PDF, with drag-and-drop reordering, a list/grid view
toggle, live thumbnails, and adjustable quality/DPI. The name's a nod to
its grid view — a "sheaf" of pictures bundled into one document.

## Features

- Supports WebP, JPEG, PNG, BMP, TIFF, GIF, and HEIC/HEIF
- Add files via a picker or by dragging them into the window
- Switch between a compact list view and a grid view with larger thumbnails
- Reorder pages by dragging rows in list view, or with the ↑ / ↓ buttons
- Remove individual files (in either view) or clear the whole queue
- Live thumbnails, a running total of queued files and source size
- Adjustable JPEG quality and output DPI (Preferences, remembered between
  launches)
- Cancel a conversion in progress
- Per-file error reporting — a corrupt or unsupported file is skipped with
  a reason shown, rather than aborting the whole batch
- Built and installed by one script that supports the major distro families,
  packaged as an AppImage with an SHA256 checksum (see "Compatibility")

## Project layout

```
picsheaf/
├── __init__.py          # __version__, APP_ID — single source of truth
├── settings.py           # AppSettings — typed GSettings wrapper
├── conversion.py          # convert_images_to_pdf() — pure, no GTK
├── thumbnails.py           # generate_thumbnails_png_bytes() — pure, no GTK
├── image_formats.py         # supported extensions/mime types, HEIC plugin registration
├── app.py                     # Adw.Application subclass
├── __main__.py                  # `python3 -m picsheaf` entrypoint
└── ui/
    ├── window.py               # main window, composes everything below
    ├── file_queue.py             # Gtk.ListStore wrapper (queue model)
    ├── preferences.py              # Preferences window
    └── about.py                     # About window

picsheaf_manager.sh   # check / setup / build / install / uninstall / clean
icon.png                  # app icon (not included — see "Before publishing")
```

`conversion.py`, `thumbnails.py`, and `image_formats.py` have zero GTK
dependency by design — they can be imported and tested with nothing but
Pillow, img2pdf, and (for HEIC) pillow-heif installed, e.g.:

```python
from picsheaf.conversion import convert_images_to_pdf

result = convert_images_to_pdf(
    ["a.webp", "b.jpg", "c.heic"], "out.pdf", quality=90, dpi=150
)
print(result.success, result.message, result.skipped)
```

## Supported formats

| Format    | Extra dependency |
|-----------|-------------------|
| WebP, JPEG, PNG, BMP, TIFF, GIF | none (Pillow + ImageMagick, both already required) |
| HEIC / HEIF | `pillow-heif` (installed automatically by `picsheaf_manager.sh build`) |

The format list lives in `picsheaf/image_formats.py` — add an extension
there (and, for a new format family, the matching Pillow plugin/dependency)
to extend it further.

## Compatibility

**Requirements on the machine that runs the app:** GTK 4.10+, libadwaita 1.4+,
PyGObject and Python 3.8+. That means releases roughly from 2023 onward —
Ubuntu 24.04+, Debian 13+, Linux Mint 22+, Fedora 39+, current Arch and
openSUSE Tumbleweed. Older releases (Ubuntu 22.04, Debian 12, Mint 21) ship
older GTK/libadwaita and can't run the app; `check` will tell you so.

**Dependency installation is automated for four package-manager families:**

| Family | Package manager | Examples |
|--------|-----------------|----------|
| Debian | `apt` | Debian, Ubuntu, Linux Mint, Pop!_OS |
| Fedora / RHEL | `dnf` | Fedora, RHEL, Rocky, AlmaLinux |
| Arch | `pacman` | Arch, Manjaro, EndeavourOS |
| SUSE | `zypper` | openSUSE Tumbleweed / Leap |

On any other system the script installs nothing, but `check` lists exactly
which capabilities are missing so you can provide them yourself. On
immutable/image-based systems (Silverblue, Kinoite, SteamOS…) it won't try to
modify the base system and points you at layering or a toolbox/distrobox
container instead.

**Tested on:** Ubuntu 24.04 (real build, install, launch, uninstall). The
dnf, pacman and zypper paths were verified with simulated distro identities
and `--dry-run` only — package names for those families are best-effort. The
script never trusts a package name: after installing, it verifies that Python
can actually import GTK4/libadwaita and that the required tools exist, and
reports precisely what's still missing. Run `./picsheaf_manager.sh check`
first on a new distro; it changes nothing.

**About the AppImage.** The AppImage bundles the app's Python packages but
relies on the host's Python interpreter and GTK4/libadwaita/PyGObject. An
AppImage built on one distro is therefore *not* guaranteed to run on another
(different Python versions, different system libraries) — build it on the
distro you'll run it on, which is what `all` does. On non-x86_64 machines, or
without `curl`, the script skips AppImage packaging and installs directly.

## Building and installing

```bash
chmod +x picsheaf_manager.sh
./picsheaf_manager.sh check    # what's this system missing? (changes nothing)
./picsheaf_manager.sh all      # setup + build + install + clean, in one step
```

Or step by step:

```bash
./picsheaf_manager.sh setup      # install system dependencies (add --dry-run to preview)
./picsheaf_manager.sh build      # produce Picsheaf-<version>-x86_64.AppImage
./picsheaf_manager.sh install    # install the app + menu entry for your user
./picsheaf_manager.sh uninstall  # remove it again
./picsheaf_manager.sh clean      # remove build artifacts
```

The script can be run from any directory. `setup` uses `sudo` (or `doas`, or
runs directly as root); if none is available it prints the exact commands to
run as root instead. Optional overrides:

| Variable | Purpose |
|----------|---------|
| `PKG_MGR=dnf` | Force a package manager (`apt`, `dnf`, `pacman`, `zypper`) |
| `PYTHON=/usr/bin/python3.12` | Use a specific interpreter. It must be able to import PyGObject, so a conda/pyenv/Homebrew Python usually won't work — the script prefers `/usr/bin/python3` for this reason |

The build runs entirely under `~/.cache/picsheaf-build` (or
`$XDG_CACHE_HOME`), a real local filesystem rather than the project
directory, since shared/network filesystems (VirtualBox shared folders, some
WSL2 mounts) don't support the permissions and loopback mounts AppImage
packaging needs.

Each successful build also writes a `.sha256` file next to the AppImage —
verify a downloaded release with:

```bash
sha256sum -c Picsheaf-<version>-x86_64.AppImage.sha256
```

## Before publishing

The app ID (`io.github.mowtiie.Picsheaf`), GSettings schema, desktop file,
and the links in the About panel all assume the repo lives at
`github.com/mowtiie/picsheaf` — update those together if that ever changes.

This repo doesn't ship an `icon.png` — add your own 256×256 PNG at the
project root before building. Without one, the build falls back to a plain
placeholder icon rather than failing.

## License

MIT — see [LICENSE](LICENSE). The license declared in the app's About
dialog and AppStream metadata should match whatever you set here.
