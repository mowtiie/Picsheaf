"""Self-update support for Picsheaf's AppImage builds.

Pure, no GTK dependency -- testable standalone, same pattern as
conversion.py and thumbnails.py. window.py owns all threading/GLib
marshaling; this module just does HTTP and file I/O and returns plain
data or raises plain exceptions.

Only the AppImage install path can self-update (see
is_running_as_appimage): the direct-install fallback (non-x86_64, or a
build machine without curl/appimagetool) has no single file to swap, so
window.py just points those users at RELEASES_PAGE instead of calling
download_and_verify/apply_update.
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

GITHUB_REPO = "mowtiie/picsheaf"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

_USER_AGENT = "Picsheaf-updater"


@dataclass
class UpdateInfo:
    version: str              # e.g. "1.1.0" -- tag with any leading 'v' stripped
    tag: str                  # the raw release tag, e.g. "v1.1.0"
    download_url: str         # the .AppImage asset
    checksum_url: str         # the matching .sha256 asset
    release_notes_url: str    # HTML page for this release
    asset_name: str


def _parse_version(tag: str):
    """'v1.2.10' -> (1, 2, 10). A non-numeric part sorts as 0 rather than
    raising, so a weird or hand-edited tag can't crash the update check --
    it just compares predictably instead of correctly."""
    cleaned = tag.lstrip("vV")
    parts = []
    for p in cleaned.split("."):
        m = re.match(r"\d+", p)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def is_newer(remote_tag: str, current_version: str) -> bool:
    return _parse_version(remote_tag) > _parse_version(current_version)


def is_running_as_appimage() -> bool:
    """The AppImage runtime sets $APPIMAGE to the running file's absolute
    path before exec'ing AppRun, and that's inherited straight through to
    this process -- a free, reliable way to tell the two install paths
    apart without any packaging-specific flag of our own."""
    return "APPIMAGE" in os.environ


def current_appimage_path() -> Optional[str]:
    return os.environ.get("APPIMAGE")


def check_for_update(current_version: str, timeout: int = 10) -> Optional[UpdateInfo]:
    """Returns UpdateInfo if a newer release with a matching AppImage
    asset (and its .sha256 sidecar) is published, else None. Never
    raises: a broken check should be invisible to the user, not an error
    dialog on every launch, so network errors, malformed responses, and
    "no matching asset" are all just treated as "no update found"."""
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag, current_version):
            return None

        assets = data.get("assets", [])
        appimage_asset = next(
            (a for a in assets if a.get("name", "").endswith("-x86_64.AppImage")), None
        )
        if appimage_asset is None:
            return None
        checksum_name = appimage_asset["name"] + ".sha256"
        checksum_asset = next(
            (a for a in assets if a.get("name", "") == checksum_name), None
        )
        if checksum_asset is None:
            return None

        return UpdateInfo(
            version=tag.lstrip("vV"),
            tag=tag,
            download_url=appimage_asset["browser_download_url"],
            checksum_url=checksum_asset["browser_download_url"],
            release_notes_url=data.get("html_url") or RELEASES_PAGE,
            asset_name=appimage_asset["name"],
        )
    except Exception:
        return None


def _expected_checksum(checksum_url: str, timeout: int) -> Optional[str]:
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        # sha256sum format: "<hex>  <filename>"
        for line in text.splitlines():
            first = line.split()[:1]
            if first and re.fullmatch(r"[0-9a-fA-F]{64}", first[0]):
                return first[0].lower()
        return None
    except Exception:
        return None


def download_and_verify(
    update: UpdateInfo,
    target_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: int = 30,
) -> str:
    """Download the update's AppImage into target_dir (the same directory
    as the file it will eventually replace, so apply_update's final swap
    is a same-filesystem, atomic rename) and verify its SHA256 against
    the published checksum. Returns the path to the verified temp file on
    success. Raises RuntimeError on any failure -- unlike
    check_for_update, the user explicitly asked for this download by
    clicking "Update Now", so a failure here is something the UI should
    actually surface, not swallow.
    """
    expected = _expected_checksum(update.checksum_url, timeout)
    if expected is None:
        raise RuntimeError("Could not verify this release's checksum, so the update was not downloaded.")

    fd, tmp_path = tempfile.mkstemp(prefix=".picsheaf-update-", dir=target_dir)
    os.close(fd)
    try:
        req = urllib.request.Request(update.download_url, headers={"User-Agent": _USER_AGENT})
        hasher = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp_path, "wb") as out:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            downloaded = 0
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    progress_cb(downloaded, total or downloaded)

        actual = hasher.hexdigest()
        if actual.lower() != expected:
            raise RuntimeError("Downloaded file did not match the published checksum.")

        return tmp_path
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def apply_update(new_path: str, target_path: str) -> None:
    """Make the downloaded file executable and atomically swap it in for
    target_path. Same-directory + os.replace() guarantees there's no
    window where target_path is half-written, and a currently-running
    instance keeps using its old, already-open inode until it exits --
    no need to stop anything before calling this."""
    os.chmod(new_path, 0o755)
    os.replace(new_path, target_path)
