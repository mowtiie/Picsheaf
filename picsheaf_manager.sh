#!/usr/bin/env bash
#
# picsheaf_manager.sh — check, set up, build, install and remove Picsheaf.
#
# Dependency installation is automated for Debian/Ubuntu (apt), Fedora/RHEL
# (dnf), Arch (pacman) and openSUSE (zypper) families. On any other system
# the script installs nothing, but `check` tells you exactly which
# capabilities are missing so you can provide them with your own tooling.
#
# Run it with no arguments for usage.

# ==========================================
#  Color Formatting
# ==========================================
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "${CYAN}${BOLD}==> $*${NC}"; }
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}"; }

# ==========================================
#  Locate the project (works from any directory, through symlinks)
# ==========================================
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null)"
[ -n "$SCRIPT_PATH" ] || SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
SELF="./$(basename "$SCRIPT_PATH")"
cd "$SCRIPT_DIR" || { echo "Cannot enter $SCRIPT_DIR" >&2; exit 1; }

APP_NAME="Picsheaf"

# App version shown in the About dialog, AppStream metadata, and the
# AppImage filename. Read straight out of picsheaf/__init__.py (no Python
# import needed, so it can't fail because of the interpreter or sys.path)
# to keep a single source of truth.
APP_VERSION=""
if [ -f "picsheaf/__init__.py" ]; then
    APP_VERSION="$(sed -nE "s/^__version__[[:space:]]*=[[:space:]]*[\"']([^\"']+)[\"'].*/\1/p" picsheaf/__init__.py | head -n 1)"
fi
if [ -z "$APP_VERSION" ]; then
    APP_VERSION="0.0.0"
    warn "Could not read __version__ from $SCRIPT_DIR/picsheaf/__init__.py — using $APP_VERSION as a placeholder."
fi

# PyGObject and the GTK4/libadwaita typelibs come from the distribution's own
# packages, so the app must run on the *system* Python — a conda/pyenv/
# Homebrew python earlier in PATH can't see them. Override with PYTHON=...
resolve_python() {
    if [ -n "${PYTHON:-}" ]; then
        PYTHON_BIN="$PYTHON"
    elif [ -x /usr/bin/python3 ]; then
        PYTHON_BIN=/usr/bin/python3
    else
        PYTHON_BIN="$(command -v python3 || true)"
    fi
}
resolve_python   # ...and again after `setup` installs Python on a minimal system

# Build everything on a real local filesystem, never in the directory the
# script happens to live in. Shared folders (VirtualBox vboxsf, 9p/Plan9
# folders in WSL2, some SMB/NFS mounts) don't support the Unix permissions,
# symlinks and loopback mounts that appimagetool needs, and that's the #1
# cause of silent AppImage build failures.
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_HOME="$HOME/.local/bin"

BUILD_ROOT="$CACHE_HOME/picsheaf-build"
APP_DIR="$BUILD_ROOT/${APP_NAME}.AppDir"
OUTPUT_APPIMAGE_NAME="${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
OUTPUT_APPIMAGE="$BUILD_ROOT/$OUTPUT_APPIMAGE_NAME"
APPIMAGETOOL="$BUILD_ROOT/appimagetool-x86_64.AppImage"
INSTALL_DIR="$DATA_HOME/picsheaf"
INSTALL_BIN="$BIN_HOME/picsheaf"
DESKTOP_ENTRY="$DATA_HOME/applications/io.github.mowtiie.Picsheaf.desktop"
ICON_ENTRY="$DATA_HOME/icons/hicolor/256x256/apps/io.github.mowtiie.Picsheaf.png"
METAINFO_ENTRY="$DATA_HOME/metainfo/io.github.mowtiie.Picsheaf.metainfo.xml"

HOST_ARCH="$(uname -m)"

# Test/override hooks (harmless in normal use)
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
IMMUTABLE_MARKER="${IMMUTABLE_MARKER:-/run/ostree-booted}"
DRY_RUN="${DRY_RUN:-0}"

# ==========================================
#  Small helpers
# ==========================================

# Hex of the first N bytes of a file — locale-independent magic-number check.
file_magic() { head -c "$2" "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n'; }

# ==========================================
#  Platform detection
# ==========================================
os_field() {
    [ -r "$OS_RELEASE_FILE" ] || return 0
    # shellcheck source=/dev/null
    ( . "$OS_RELEASE_FILE" >/dev/null 2>&1; printf '%s' "${!1:-}" )
}

detect_platform() {
    DISTRO_NAME="$(os_field PRETTY_NAME)"
    [ -n "$DISTRO_NAME" ] || DISTRO_NAME="an unrecognised Linux distribution"

    if [ -n "${PKG_MGR:-}" ]; then
        # explicit override from the environment — only known managers are usable
        case "$PKG_MGR" in
            apt|dnf|pacman|zypper) ;;
            *) warn "Unsupported PKG_MGR='$PKG_MGR' (use apt, dnf, pacman or zypper) — treating this system as unrecognised."
               PKG_MGR=unknown ;;
        esac
    elif command -v apt-get >/dev/null 2>&1; then
        PKG_MGR=apt
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MGR=dnf
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MGR=pacman
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MGR=zypper
    else
        PKG_MGR=unknown
    fi

    IMMUTABLE=0
    [ -e "$IMMUTABLE_MARKER" ] && IMMUTABLE=1
}

# Decide how to gain root for package installation.
setup_privilege() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    elif command -v doas >/dev/null 2>&1; then
        SUDO="doas"
    else
        SUDO="__none__"
    fi
}

run_priv() {
    if [ "$DRY_RUN" = 1 ]; then
        # PLAN_PREFIX defaults to "[dry-run] "; setting it to empty prints
        # plain commands (used when telling a user what to run as root).
        local shown="" label="${PLAN_PREFIX-[dry-run] }"
        [ -n "$SUDO" ] && [ "$SUDO" != "__none__" ] && shown="$SUDO "
        echo "    ${label}${shown}$*"
        return 0
    fi
    [ "$SUDO" = "__none__" ] && return 126
    $SUDO "$@"
}

# ==========================================
#  Package names per package manager
# ==========================================
# PKGS_CORE     — required; the app cannot build or run without them.
# PKGS_OPTIONAL — nice to have; the script degrades gracefully without them.
#
# Names are best-effort per distro; they are never trusted blindly. After
# installing, check_deps verifies the *capabilities* (can Python import
# GTK4? is glib-compile-schemas on PATH?), so a wrong or renamed package name
# is reported precisely instead of silently producing a broken build.
select_packages() {
    PKGS_CORE=()
    PKGS_OPTIONAL=()
    case "$1" in
        apt)
            local fuse=libfuse2
            apt-cache show libfuse2t64 >/dev/null 2>&1 && fuse=libfuse2t64
            PKGS_CORE=(python3 python3-venv python3-pip python3-gi python3-gi-cairo
                       gir1.2-glib-2.0 gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0
                       libglib2.0-bin)
            PKGS_OPTIONAL=(curl desktop-file-utils imagemagick file "$fuse")
            ;;
        dnf)
            # curl is deliberately absent: Fedora/RHEL ship curl-minimal, which
            # conflicts with the full curl package and already provides /usr/bin/curl.
            PKGS_CORE=(python3 python3-pip python3-gobject gtk4 libadwaita
                       gdk-pixbuf2 glib2)
            PKGS_OPTIONAL=(desktop-file-utils ImageMagick file fuse-libs)
            ;;
        pacman)
            PKGS_CORE=(python python-pip python-gobject gtk4 libadwaita
                       gdk-pixbuf2 glib2)
            PKGS_OPTIONAL=(curl desktop-file-utils imagemagick file fuse2)
            ;;
        zypper)
            PKGS_CORE=(python3 python3-pip python3-gobject python3-gobject-Gdk
                       typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 typelib-1_0-GdkPixbuf-2_0
                       glib2-tools)
            PKGS_OPTIONAL=(curl desktop-file-utils ImageMagick file libfuse2)
            ;;
    esac
}

pm_refresh() {
    case "$PKG_MGR" in
        apt) run_priv apt-get update ;;
        *)   : ;;   # dnf/zypper refresh on demand; never `pacman -Sy` (partial upgrades)
    esac
}

pm_install() {
    case "$PKG_MGR" in
        apt)    run_priv env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        dnf)    run_priv dnf install -y "$@" ;;
        pacman) run_priv pacman -S --needed --noconfirm "$@" ;;
        zypper) run_priv zypper --non-interactive install "$@" ;;
        *)      return 1 ;;
    esac
}

# Install a group of packages. If the bulk install fails (typically one
# unknown package name aborting the whole transaction), retry one at a time
# so a single bad name doesn't block everything else.
install_group() {
    local label="$1"; shift
    [ $# -gt 0 ] || return 0
    echo -e "  ${YELLOW}• Installing $label packages: $*${NC}"
    pm_install "$@" && return 0
    warn "Bulk install of $label packages failed; retrying one at a time to find the culprit(s)..."
    local p
    for p in "$@"; do
        if pm_install "$p" >/dev/null 2>&1; then
            echo "    ✔ $p"
        else
            echo "    ✖ $p"
            FAILED_PKGS+=("$p")
        fi
    done
}

# ==========================================
#  Capability checks
# ==========================================
_report() {   # kind (ok|miss_req|miss_opt), label, detail
    case "$1" in
        ok)
            if [ "$CHECK_MODE" = verbose ]; then
                echo -e "  ${GREEN}✔${NC} $2${3:+ ($3)}"
            fi
            ;;
        miss_req)
            echo -e "  ${RED}✖${NC} $2${3:+ — $3}"
            MISSING_REQUIRED+=("$2")
            ;;
        miss_opt)
            echo -e "  ${YELLOW}○${NC} $2${3:+ — $3}"
            MISSING_OPTIONAL+=("$2")
            ;;
    esac
}

_have_fuse2() {
    local ldc
    ldc="$(command -v ldconfig 2>/dev/null)"
    [ -n "$ldc" ] || for ldc in /sbin/ldconfig /usr/sbin/ldconfig; do [ -x "$ldc" ] && break; done
    [ -x "$ldc" ] && "$ldc" -p 2>/dev/null | grep -q 'libfuse\.so\.2'
}

# check_deps [verbose|quiet]  — returns 0 when every REQUIRED capability is
# present. Optional gaps are reported but don't affect the return value.
check_deps() {
    CHECK_MODE="${1:-verbose}"
    MISSING_REQUIRED=()
    MISSING_OPTIONAL=()

    local have_python=0
    if [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        have_python=1
        _report ok "Python" "$("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    else
        _report miss_req "Python 3.8 or newer" "not found or too old — if your distro's default is older, point PYTHON=/path/to/python3.x at a newer one"
    fi

    if [ "$have_python" = 1 ]; then
        local tmp_venv
        tmp_venv="$(mktemp -d)"
        if "$PYTHON_BIN" -m venv "$tmp_venv/v" >/dev/null 2>&1 && [ -x "$tmp_venv/v/bin/pip" ]; then
            _report ok "Python venv + pip"
        else
            _report miss_req "Python venv + pip" "e.g. python3-venv and python3-pip on Debian/Ubuntu"
        fi
        rm -rf "$tmp_venv"

        local gi_out
        gi_out="$("$PYTHON_BIN" - 2>/dev/null <<'PYEOF'
import sys
try:
    import gi
except ImportError:
    print("NOGI")
    sys.exit(0)
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkPixbuf", "2.0")
except ValueError as exc:
    print("NOTYPELIB", exc)
    sys.exit(0)
from gi.repository import Gtk, Adw
gtk = "%d.%d" % (Gtk.get_major_version(), Gtk.get_minor_version())
adw = "%d.%d" % (Adw.MAJOR_VERSION, Adw.MINOR_VERSION)
# The APIs the app actually uses that arrived latest: Gtk.FileDialog (GTK 4.10)
# and Adw.SpinRow (libadwaita 1.4).
ok = hasattr(Gtk, "FileDialog") and hasattr(Adw, "SpinRow")
print("OK" if ok else "TOOOLD", gtk, adw)
PYEOF
)"
        local gi_status gi_a gi_b
        read -r gi_status gi_a gi_b <<< "$gi_out"
        case "$gi_status" in
            OK)
                _report ok "PyGObject + GTK4 + libadwaita" "GTK $gi_a, libadwaita $gi_b" ;;
            NOGI)
                _report miss_req "PyGObject (Python bindings for GTK)" "not importable from $PYTHON_BIN" ;;
            NOTYPELIB)
                _report miss_req "GTK 4 / libadwaita / GdkPixbuf typelibs" "${gi_out#NOTYPELIB }" ;;
            TOOOLD)
                _report miss_req "GTK 4.10+ and libadwaita 1.4+" "found GTK $gi_a and libadwaita $gi_b — this release of your distro is too old for the app" ;;
            *)
                _report miss_req "PyGObject + GTK4 + libadwaita" "could not import them from $PYTHON_BIN" ;;
        esac
    fi

    if command -v glib-compile-schemas >/dev/null 2>&1; then
        _report ok "glib-compile-schemas"
    else
        _report miss_req "glib-compile-schemas" "without it, preferences and window size wouldn't persist"
    fi

    if command -v curl >/dev/null 2>&1; then
        _report ok "curl"
    else
        _report miss_opt "curl" "needed to download appimagetool; without it the app is installed directly instead of as an AppImage"
    fi

    if command -v update-desktop-database >/dev/null 2>&1; then
        _report ok "desktop-file-utils"
    else
        _report miss_opt "desktop-file-utils" "the app menu may need a re-login to show the new entry"
    fi

    if command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; then
        _report ok "ImageMagick"
    else
        _report miss_opt "ImageMagick" "not needed — Pillow handles every format itself"
    fi

    if _have_fuse2; then
        _report ok "FUSE 2 (libfuse.so.2)"
    else
        _report miss_opt "FUSE 2 (libfuse.so.2)" "needed to run an AppImage directly; otherwise start it with --appimage-extract-and-run"
    fi

    [ "${#MISSING_REQUIRED[@]}" -eq 0 ]
}

print_manual_guidance() {
    echo ""
    if [ "$IMMUTABLE" = 1 ]; then
        warn "This looks like an immutable / image-based system (${DISTRO_NAME}); packages can't be installed into the base system with $PKG_MGR here."
        echo "  Options: layer the missing packages with your system's tool (for example"
        echo "  'rpm-ostree install ...'), or run this script inside a regular container such"
        echo "  as toolbox or distrobox, then run '$SELF check' again."
    elif [ "$PKG_MGR" = unknown ]; then
        warn "No supported package manager (apt, dnf, pacman, zypper) was found on ${DISTRO_NAME}."
        echo "  Install the equivalents of the ✖ items above using your own package manager,"
        echo "  then run '$SELF build'. For reference, the required packages elsewhere are:"
        local m
        for m in apt dnf pacman zypper; do
            select_packages "$m"
            echo "    $m: ${PKGS_CORE[*]}"
        done
    else
        echo "  Run '$SELF setup' to install what's missing."
    fi
}

check_command() {
    step "Checking this system"
    detect_platform
    echo "  Distribution    : $DISTRO_NAME"
    echo "  Package manager : $PKG_MGR$([ "$IMMUTABLE" = 1 ] && echo ' (immutable system)')"
    echo "  Architecture    : $HOST_ARCH"
    echo ""
    if check_deps verbose; then
        echo ""
        ok "All required dependencies are present."
        [ "${#MISSING_OPTIONAL[@]}" -eq 0 ] || echo "  (Optional items marked ○ can be installed with '$SELF setup'.)"
        return 0
    fi
    print_manual_guidance
    return 1
}

# ==========================================
#  1. Install system dependencies
# ==========================================
setup_env() {
    step "Setting up system dependencies"
    detect_platform
    setup_privilege
    echo "  Distribution    : $DISTRO_NAME"
    echo "  Package manager : $PKG_MGR$([ "$IMMUTABLE" = 1 ] && echo ' (immutable system)')"
    echo ""

    if [ "$IMMUTABLE" = 1 ] || [ "$PKG_MGR" = unknown ]; then
        if check_deps verbose; then
            ok "All required dependencies are already present.\n"
            return 0
        fi
        print_manual_guidance
        return 1
    fi

    select_packages "$PKG_MGR"

    # Skip privileged work entirely when nothing is missing (dry runs still
    # show the plan).
    if [ "$DRY_RUN" != 1 ] && check_deps quiet && [ "${#MISSING_OPTIONAL[@]}" -eq 0 ]; then
        ok "Everything is already installed — nothing to do.\n"
        return 0
    fi

    if [ "$DRY_RUN" != 1 ] && [ "$SUDO" = "__none__" ]; then
        err "Packages are missing, but you're not root and neither sudo nor doas is available."
        echo "  Run these commands as root, then re-run '$SELF setup':"
        PLAN_PREFIX='' DRY_RUN=1 install_flow
        return 1
    fi

    install_flow

    echo ""
    if [ "$DRY_RUN" = 1 ]; then
        echo "  (dry run — nothing was installed)"
        return 0
    fi

    resolve_python   # a minimal system had no Python until just now
    echo "  Verifying the result..."
    if check_deps verbose; then
        echo ""
        if [ "${#FAILED_PKGS[@]}" -gt 0 ]; then
            warn "Not available from your repositories, so skipped: ${FAILED_PKGS[*]}"
            echo "  Everything required is present, so this is fine$([ "${#MISSING_OPTIONAL[@]}" -gt 0 ] && echo ' — see the ○ items above for what it affects')."
        fi
        ok "System dependencies ready.\n"
        return 0
    fi

    echo ""
    err "Some required dependencies are still missing."
    if [ "${#FAILED_PKGS[@]}" -gt 0 ]; then
        echo "  Packages that could not be installed: ${FAILED_PKGS[*]}"
        echo "  (Package names differ between releases — search your repositories for the"
        echo "  ✖ items above and install them by hand.)"
    fi
    if [ "$PKG_MGR" = pacman ]; then
        echo "  On Arch, 404s or 'target not found' usually mean a stale package database: run"
        echo "  'sudo pacman -Syu' and try again."
    fi
    return 1
}

install_flow() {
    FAILED_PKGS=()
    pm_refresh
    # Choose package names only now: on a fresh system (e.g. a minimal
    # container) the apt lists are empty until the refresh above, and the
    # right libfuse2 package name is discovered by querying them.
    select_packages "$PKG_MGR"
    install_group "required" "${PKGS_CORE[@]}"
    install_group "optional" "${PKGS_OPTIONAL[@]}"
}

# ==========================================
#  2. Bundle application & attempt AppImage packaging
# ==========================================
build_appimage() {
    if [ ! -f "picsheaf/__main__.py" ]; then
        err "picsheaf/__main__.py not found next to $SELF — the picsheaf/ package must sit in the same directory as this script."
        exit 1
    fi

    detect_platform
    if ! check_deps quiet; then
        err "Required dependencies are missing (see above)."
        print_manual_guidance
        exit 1
    fi

    step "Preparing Application Bundle (v$APP_VERSION)..."

    # Warn if the project directory itself looks like a shared/network mount,
    # since the picsheaf/ package and icon.png are still read from here even
    # though the build output lives under $BUILD_ROOT.
    CWD_FSTYPE=$(stat -f -c %T . 2>/dev/null || echo "unknown")
    case "$CWD_FSTYPE" in
        vboxsf|9p|cifs|nfs|smb*)
            warn "The project directory is on a '${CWD_FSTYPE}' filesystem. That's fine for reading the source, but if you still see failures, copy the whole project to a local directory (e.g. ~/picsheaf-src) and run the script from there."
            ;;
    esac

    # Clean old artifacts and set up a fresh local build root
    rm -rf "$BUILD_ROOT"
    mkdir -p "$BUILD_ROOT"

    # Create directory tree
    mkdir -p "$APP_DIR/usr/bin"
    mkdir -p "$APP_DIR/usr/lib"
    mkdir -p "$APP_DIR/usr/lib/picsheaf-src"
    mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
    mkdir -p "$APP_DIR/usr/share/glib-2.0/schemas"
    mkdir -p "$APP_DIR/usr/share/metainfo"
    mkdir -p "$APP_DIR/usr/share/applications"

    # GSettings schema — bundled and compiled into the AppDir itself
    # (GSETTINGS_SCHEMA_DIR is pointed at this directory by AppRun below),
    # so preferences work without installing anything system-wide.
    echo -e "  ${YELLOW}• Compiling GSettings schema...${NC}"
    cat << 'EOF' > "$APP_DIR/usr/share/glib-2.0/schemas/io.github.mowtiie.Picsheaf.gschema.xml"
<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="io.github.mowtiie.Picsheaf" path="/io/github/mowtiie/Picsheaf/">
    <key name="last-add-folder" type="s">
      <default>''</default>
      <summary>Last folder used to add image files</summary>
    </key>
    <key name="last-save-folder" type="s">
      <default>''</default>
      <summary>Last folder used to save the output PDF</summary>
    </key>
    <key name="window-width" type="i">
      <default>680</default>
      <summary>Saved window width</summary>
    </key>
    <key name="window-height" type="i">
      <default>560</default>
      <summary>Saved window height</summary>
    </key>
    <key name="jpeg-quality" type="i">
      <range min="1" max="100"/>
      <default>90</default>
      <summary>JPEG quality used for the intermediate image conversion</summary>
    </key>
    <key name="output-dpi" type="i">
      <range min="72" max="600"/>
      <default>150</default>
      <summary>DPI used to size pages in the output PDF</summary>
    </key>
    <key name="auto-check-updates" type="b">
      <default>true</default>
      <summary>Automatically check GitHub for new Picsheaf releases on launch</summary>
    </key>
    <key name="skip-update-version" type="s">
      <default>''</default>
      <summary>A release version to stop notifying about until a newer one is published</summary>
    </key>
  </schema>
</schemalist>
EOF
    glib-compile-schemas "$APP_DIR/usr/share/glib-2.0/schemas/"

    # AppStream metadata — describes the app for software centers.
    # NOTE: the homepage URL below assumes the repo lives at
    # github.com/mowtiie/picsheaf — update it if that ever changes.
    TODAY=$(date +%Y-%m-%d)
    cat << EOF > "$APP_DIR/usr/share/metainfo/io.github.mowtiie.Picsheaf.metainfo.xml"
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.github.mowtiie.Picsheaf</id>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <name>Picsheaf</name>
  <summary>Convert images into a single PDF document</summary>
  <description>
    <p>
      Picsheaf lets you select one or more images, reorder them,
      and combine them into a single PDF document.
    </p>
  </description>
  <launchable type="desktop-id">io.github.mowtiie.Picsheaf.desktop</launchable>
  <url type="homepage">https://github.com/mowtiie/picsheaf</url>
  <developer id="io.github.mowtiie">
    <name>Picsheaf Project</name>
  </developer>
  <releases>
    <release version="$APP_VERSION" date="$TODAY"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF
    # Some appimagetool builds (this one included) still look for the
    # pre-2020 AppStream filename (.appdata.xml) rather than the current
    # .metainfo.xml convention, and warn if it's absent even though the
    # correct file exists. Satisfy both rather than fighting the warning.
    cp "$APP_DIR/usr/share/metainfo/io.github.mowtiie.Picsheaf.metainfo.xml" \
       "$APP_DIR/usr/share/metainfo/io.github.mowtiie.Picsheaf.appdata.xml"

    # Copy the application package. $HERE/usr/lib/picsheaf-src gets added
    # to PYTHONPATH by AppRun so `import picsheaf` resolves.
    cp -r picsheaf "$APP_DIR/usr/lib/picsheaf-src/"

    # Bundle Python virtual environment with dependencies.
    # --system-site-packages is required: PyGObject ("gi") and the GTK4/
    # libadwaita typelibs come from the distribution's packages and cannot
    # be pip-installed, so the venv must be able to see the system
    # site-packages to find them.
    echo -e "  ${YELLOW}• Bundling Python Virtual Environment...${NC}"
    if ! "$PYTHON_BIN" -m venv --system-site-packages "$APP_DIR/usr/venv"; then
        err "Could not create a Python virtual environment with $PYTHON_BIN (on Debian/Ubuntu this needs the python3-venv package)."
        exit 1
    fi
    "$APP_DIR/usr/venv/bin/pip" install --quiet --upgrade pip
    if ! "$APP_DIR/usr/venv/bin/pip" install --quiet img2pdf Pillow; then
        err "pip could not install img2pdf/Pillow — check your internet connection (PyPI) and try again."
        exit 1
    fi
    # HEIC/HEIF support is optional: pillow-heif may have no prebuilt wheel
    # for very new Python versions. The app runs fine without it.
    if ! "$APP_DIR/usr/venv/bin/pip" install --quiet pillow-heif; then
        warn "Could not install pillow-heif — the app will build without HEIC/HEIF support."
    fi

    # Sanity check: fail loudly here (during build) rather than at runtime
    # if the venv can't import the app package or PyGObject/GTK4/Adwaita.
    # This exercises the exact import chain AppRun will use.
    SANITY_CHECK=$(PYTHONPATH="$APP_DIR/usr/lib/picsheaf-src" "$APP_DIR/usr/venv/bin/python3" -c "
import picsheaf
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
from picsheaf.app import PicsheafApp
from picsheaf.image_formats import HEIF_SUPPORTED, SUPPORTED_FORMATS
from picsheaf import updater
print('OK', picsheaf.__version__, 'HEIF_SUPPORTED=' + str(HEIF_SUPPORTED), 'formats=' + str(len(SUPPORTED_FORMATS)), 'updater=' + updater.__name__)
" 2>&1)
    if [[ "$SANITY_CHECK" == OK* ]]; then
        echo -e "  ${GREEN}• Import sanity check passed ($SANITY_CHECK)${NC}"
    else
        err "Bundled venv failed to import the app (run '$SELF check' to see what's missing)."
        echo -e "${RED}   Details: $SANITY_CHECK${NC}"
    fi

    # Bundle ImageMagick (optional accelerator; the app falls back to Pillow
    # when `convert` isn't available).
    MAGICK_BIN=$(command -v magick || command -v convert || true)
    if [ -n "$MAGICK_BIN" ]; then
        echo -e "  ${YELLOW}• Bundling ImageMagick & C libraries...${NC}"
        cp "$MAGICK_BIN" "$APP_DIR/usr/bin/convert"
        ldd "$MAGICK_BIN" 2>/dev/null | grep "=> /" | awk '{print $3}' | while read -r lib; do
            if [ -f "$lib" ]; then
                cp -n "$lib" "$APP_DIR/usr/lib/" 2>/dev/null || true
            fi
        done
    else
        echo -e "  ${YELLOW}• ImageMagick not installed — skipping (Pillow will do all conversions).${NC}"
    fi

    # Create Desktop File.
    # Note: "Version" below is the Desktop Entry Specification version this
    # file conforms to (per freedesktop.org spec), NOT the app's own
    # version — that's tracked separately via X-AppVersion, the AppImage
    # filename, and the AppStream metainfo release above.
    cat << EOF > "$APP_DIR/io.github.mowtiie.Picsheaf.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Picsheaf
Comment=Convert images into a single PDF document
Exec=AppRun
Icon=io.github.mowtiie.Picsheaf
Terminal=false
Categories=Graphics;2DGraphics;
X-AppVersion=$APP_VERSION
EOF

    # AppStream's desktop-id launchable resolves against the standard XDG
    # path, not the AppImage-runtime copy at the AppDir root.
    cp "$APP_DIR/io.github.mowtiie.Picsheaf.desktop" "$APP_DIR/usr/share/applications/io.github.mowtiie.Picsheaf.desktop"

    # App Icon. Use the project's icon.png if present; otherwise generate a
    # plain neutral placeholder locally (no network dependency).
    ICON_TARGET="$APP_DIR/io.github.mowtiie.Picsheaf.png"
    if [ -f "icon.png" ] && [ "$(file_magic icon.png 4)" = "89504e47" ]; then
        cp icon.png "$ICON_TARGET"
    else
        if [ -f "icon.png" ]; then
            warn "icon.png exists but isn't a valid PNG — using a placeholder icon instead."
        else
            warn "No icon.png found next to the script — using a plain placeholder icon. Add your own 256x256 icon.png and rebuild."
        fi
        "$APP_DIR/usr/venv/bin/python3" -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, 255, 255], radius=56, fill=(61, 111, 181, 255))
d.rounded_rectangle([72, 56, 184, 200], radius=10, fill=(255, 255, 255, 255))
img.save('$ICON_TARGET')
"
    fi
    cp "$ICON_TARGET" "$APP_DIR/.DirIcon" 2>/dev/null || true

    # AppRun entrypoint. Plain /bin/sh (no bashisms) so it also starts on
    # systems without /bin/bash; ${VAR:+...} avoids leaving an empty entry
    # in LD_LIBRARY_PATH/PYTHONPATH, which would mean "the current directory".
    cat << 'EOF' > "$APP_DIR/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$HERE/usr/venv/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GSETTINGS_SCHEMA_DIR="$HERE/usr/share/glib-2.0/schemas"
export PYTHONPATH="$HERE/usr/lib/picsheaf-src${PYTHONPATH:+:$PYTHONPATH}"
exec "$HERE/usr/venv/bin/python3" -m picsheaf "$@"
EOF
    chmod +x "$APP_DIR/AppRun"

    # ---- AppImage packaging (x86_64 only; other architectures get a direct install) ----
    APPIMAGETOOL_STATUS=1
    PACKAGE_NOTE=""
    if [ "$HOST_ARCH" != "x86_64" ]; then
        PACKAGE_NOTE="AppImage packaging is only set up for x86_64 (this machine is $HOST_ARCH)."
    elif ! command -v curl >/dev/null 2>&1; then
        PACKAGE_NOTE="curl is not installed, so appimagetool can't be downloaded."
    else
        # Download appimagetool if not already cached locally
        if [ ! -f "$APPIMAGETOOL" ]; then
            echo -e "  ${YELLOW}• Downloading appimagetool via curl...${NC}"
            curl -sSL -o "$APPIMAGETOOL" "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
            # Verify we actually got the ELF binary, not a GitHub error/HTML page
            if [ ! -f "$APPIMAGETOOL" ] || [ "$(file_magic "$APPIMAGETOOL" 4)" != "7f454c46" ]; then
                err "Downloaded appimagetool doesn't look like a valid binary (got an error page instead — check network/proxy access to github.com)."
                rm -f "$APPIMAGETOOL"
                PACKAGE_NOTE="appimagetool could not be downloaded."
            else
                chmod +x "$APPIMAGETOOL"
            fi
        fi

        # Compile AppImage — errors are shown (not silenced) so real failures are visible.
        # --appimage-extract-and-run must come first: it's handled by the
        # AppImage runtime wrapping appimagetool itself (so FUSE isn't needed
        # to *build*). --no-appstream: we ship correct AppStream metadata for
        # software centers, but appimagetool's own validator (active whenever
        # appstreamcli is installed) does a live network check on the
        # homepage URL and would fail the whole build if it's unreachable.
        if [ -f "$APPIMAGETOOL" ]; then
            echo -e "  ${YELLOW}• Compiling AppImage package...${NC}"
            ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --no-appstream "$APP_DIR" "$OUTPUT_APPIMAGE"
            APPIMAGETOOL_STATUS=$?
        fi
    fi

    if [ -f "$OUTPUT_APPIMAGE" ] && [ "$APPIMAGETOOL_STATUS" -eq 0 ]; then
        # Also drop a copy next to the picsheaf/ source for convenience
        cp "$OUTPUT_APPIMAGE" "./$OUTPUT_APPIMAGE_NAME" 2>/dev/null || true
        ok "AppImage created: $OUTPUT_APPIMAGE"

        # Publish a checksum so anyone you share the AppImage with can
        # verify it wasn't tampered with in transit.
        CHECKSUM=$(sha256sum "$OUTPUT_APPIMAGE" | awk '{print $1}')
        echo "$CHECKSUM  $OUTPUT_APPIMAGE_NAME" > "$BUILD_ROOT/$OUTPUT_APPIMAGE_NAME.sha256"
        cp "$BUILD_ROOT/$OUTPUT_APPIMAGE_NAME.sha256" "./$OUTPUT_APPIMAGE_NAME.sha256" 2>/dev/null || true
        ok "SHA256: $CHECKSUM\n"
    else
        if [ -n "$PACKAGE_NOTE" ]; then
            warn "$PACKAGE_NOTE Falling back to a direct (non-AppImage) installation."
            echo ""
        else
            warn "AppImage packaging failed (exit code $APPIMAGETOOL_STATUS — see the appimagetool output above for the real reason). Falling back to a direct (non-AppImage) installation."
            echo -e "${YELLOW}  Most common cause: building on a shared/network filesystem or a container without /dev/fuse.${NC}\n"
        fi
    fi
}

# ==========================================
#  3. Integrate into the user's menu and PATH
# ==========================================
ensure_path() {
    case ":$PATH:" in
        *":$BIN_HOME:"*) return 0 ;;
    esac

    local rc line
    # The single quotes are deliberate: the rc file must contain the literal
    # text $HOME/.local/bin so it expands when the shell starts, not now.
    # shellcheck disable=SC2016
    case "$(basename "${SHELL:-bash}")" in
        zsh)  rc="$HOME/.zshrc"; line='export PATH="$HOME/.local/bin:$PATH"' ;;
        fish) rc="$HOME/.config/fish/conf.d/picsheaf.fish"; line='fish_add_path -g $HOME/.local/bin' ;;
        *)    rc="$HOME/.bashrc"; line='export PATH="$HOME/.local/bin:$PATH"' ;;
    esac

    mkdir -p "$(dirname "$rc")"
    # Any existing mention of ~/.local/bin means the user already handles it.
    if ! { [ -f "$rc" ] && grep -qF '.local/bin' "$rc"; }; then
        echo "$line" >> "$rc"
        echo -e "  ${YELLOW}• Added ~/.local/bin to your PATH in $rc — open a new terminal to pick it up.${NC}"
    fi
    export PATH="$BIN_HOME:$PATH"
}

install_app() {
    step "Installing Application..."

    mkdir -p "$BIN_HOME"
    mkdir -p "$DATA_HOME/applications"
    mkdir -p "$DATA_HOME/icons/hicolor/256x256/apps"
    mkdir -p "$DATA_HOME/metainfo"

    if [ -f "$OUTPUT_APPIMAGE" ]; then
        # Standard AppImage Installation
        cp "$OUTPUT_APPIMAGE" "$INSTALL_BIN"
        chmod +x "$INSTALL_BIN"
    else
        # Direct Directory Fallback Installation
        if [ ! -d "$APP_DIR" ]; then
            err "AppDir missing. Run '$SELF build' first."
            exit 1
        fi
        rm -rf "$INSTALL_DIR"
        mkdir -p "$INSTALL_DIR"
        cp -r "$APP_DIR"/* "$INSTALL_DIR/"

        # Symlink AppRun entrypoint to user PATH
        ln -sf "$INSTALL_DIR/AppRun" "$INSTALL_BIN"
    fi

    # Copy Icon
    cp "$APP_DIR/io.github.mowtiie.Picsheaf.png" "$ICON_ENTRY" 2>/dev/null || true

    # Install AppStream metadata (lets GNOME Software / KDE Discover /
    # other software centers discover the app; harmless otherwise)
    cp "$APP_DIR/usr/share/metainfo/io.github.mowtiie.Picsheaf.metainfo.xml" "$METAINFO_ENTRY" 2>/dev/null || true

    # Install Desktop Entry.
    # Note: "Version" below is the Desktop Entry Specification version this
    # file conforms to, NOT the app's own version — see X-AppVersion.
    cat << EOF > "$DESKTOP_ENTRY"
[Desktop Entry]
Version=1.0
Type=Application
Name=Picsheaf
Comment=Convert images into a single PDF document
Exec=$INSTALL_BIN
Icon=io.github.mowtiie.Picsheaf
Terminal=false
Categories=Graphics;2DGraphics;
X-AppVersion=$APP_VERSION
EOF

    ensure_path

    # Refresh the application launcher database (when the tool exists)
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
    fi

    ok "Installation Complete!"
    echo -e "${BOLD}Try running:${NC} picsheaf"
    echo -e "Or search for ${BOLD}'Picsheaf'${NC} in your application menu.\n"
}

# ==========================================
#  4. Uninstall
# ==========================================
uninstall_app() {
    step "Uninstalling Picsheaf..."
    rm -f "$INSTALL_BIN" "$DESKTOP_ENTRY" "$ICON_ENTRY" "$METAINFO_ENTRY"
    rm -rf "$INSTALL_DIR"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
    fi
    ok "Application uninstalled.\n"
}

# ==========================================
#  5. Clean build files
# ==========================================
clean_up() {
    step "Cleaning build directory..."
    rm -rf "$APP_DIR" "$APPIMAGETOOL"
    ok "Cleaned.\n"
}

# ==========================================
#  CLI
# ==========================================
usage() {
    echo -e "${BOLD}Usage:${NC} $SELF <command> [--dry-run]"
    echo ""
    echo "Commands:"
    echo -e "  ${CYAN}check${NC}      - Report this system's distro, package manager and missing dependencies"
    echo -e "  ${CYAN}setup${NC}      - Install system dependencies (apt, dnf, pacman or zypper)"
    echo -e "  ${CYAN}build${NC}      - Package the picsheaf/ app and runtime dependencies"
    echo -e "  ${CYAN}install${NC}    - Install the app and its menu entry for the current user"
    echo -e "  ${CYAN}uninstall${NC}  - Remove the app and its menu entry"
    echo -e "  ${CYAN}clean${NC}      - Remove temporary build artifacts"
    echo -e "  ${CYAN}all${NC}        - setup + build + install + clean in one step"
    echo ""
    echo "Options / environment:"
    echo "  --dry-run       With 'setup': print the package commands instead of running them"
    echo "  PKG_MGR=...     Force a package manager (apt, dnf, pacman, zypper)"
    echo "  PYTHON=...      Use this Python interpreter (must be able to import PyGObject)"
    echo ""
}

main() {
    local cmd="${1:-}"
    [ $# -gt 0 ] && shift
    local arg
    for arg in "$@"; do
        [ "$arg" = "--dry-run" ] && DRY_RUN=1
    done

    case "$cmd" in
        check)     check_command ;;
        setup)     setup_env ;;
        build)     build_appimage ;;
        install)   install_app ;;
        uninstall) uninstall_app ;;
        clean)     clean_up ;;
        all)       setup_env && build_appimage && install_app && clean_up ;;
        *)         usage; [ -z "$cmd" ] ;;   # bare invocation: usage, exit 0; unknown command: exit 1
    esac
}

# Only run when executed, not when sourced (so the functions can be tested).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
    exit $?
fi
