<div align="center">

<img width="" src="icon.png"  width=160 height=160  align="center">

# Picsheaf

A native GTK4 / Libadwaita desktop app for Linux that converts one or more
images into a single PDF, with drag-and-drop reordering, a list/grid view
toggle, live thumbnails, and adjustable quality/DPI.
</div>

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
- Per-file error reporting  a corrupt or unsupported file is skipped with
  a reason shown, rather than aborting the whole batch

## Supported formats

| Format    | Extra dependency |
|-----------|-------------------|
| WebP, JPEG, PNG, BMP, TIFF, GIF | none (Pillow + ImageMagick, both already required) |
| HEIC / HEIF | `pillow-heif` (installed automatically by `picsheaf_manager.sh build`) |

The format list lives in `picsheaf/image_formats.py`  add an extension
there (and, for a new format family, the matching Pillow plugin/dependency)
to extend it further.

## Compatibility

**Requirements on the machine that runs the app:** GTK 4.10+, libadwaita 1.4+,
PyGObject and Python 3.8+. That means releases roughly from 2023 onward 
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

## Verification

### PGP Signing

**Public key fingerprint:**
```
9EA2 8F46 7802 5092 7643 1B69 42B5 FA42 AA63 90E1
```

Download and import the key from my website, or directly from this repo:

```
curl -O https://mowtiie.cc/PGP_PUBLIC_KEY.asc
gpg --import PGP_PUBLIC_KEY.asc
```

After importing, confirm the fingerprint printed by GPG matches the one listed above  that match is what actually establishes trust, not the import step itself. Fetching the key over HTTPS from a domain you already trust is arguably a stronger anchor than a keyserver, since keyservers accept uploads from anyone and don't vouch for identity.

Each release includes a detached `.asc` signature alongside the APK. Verify a downloaded release with:

```
gpg --verify Picsheaf-vX.X.X-x86_64.AppImage.asc Picsheaf-vX.X.X-x86_64.AppImage
```

A valid signature looks like:

```
Good signature from "Mowtiie <mowtiie.dev@gmail.com>"
```

Each successful build also writes a `.sha256` file next to the AppImage 
verify a downloaded release with:

```bash
sha256sum -c Picsheaf-<version>-x86_64.AppImage.sha256
```

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
| `PYTHON=/usr/bin/python3.12` | Use a specific interpreter. It must be able to import PyGObject, so a conda/pyenv/Homebrew Python usually won't work  the script prefers `/usr/bin/python3` for this reason |

The build runs entirely under `~/.cache/picsheaf-build` (or
`$XDG_CACHE_HOME`), a real local filesystem rather than the project
directory, since shared/network filesystems (VirtualBox shared folders, some
WSL2 mounts) don't support the permissions and loopback mounts AppImage
packaging needs.

## License

MIT  see [LICENSE](LICENSE). The license declared in the app's About
dialog and AppStream metadata should match whatever you set here.
