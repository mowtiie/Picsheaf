"""Application settings, backed by GSettings with an in-memory fallback.

Every GSettings key name lives in exactly one place (this file) behind
named properties, so a typo in a key string is a Python AttributeError
at the call site instead of a silently-ignored no-op.
"""
from gi.repository import Gio

from picsheaf import APP_ID

DEFAULT_JPEG_QUALITY = 90
DEFAULT_OUTPUT_DPI = 150
DEFAULT_WINDOW_WIDTH = 680
DEFAULT_WINDOW_HEIGHT = 560
DEFAULT_AUTO_CHECK_UPDATES = True

_FALLBACK_DEFAULTS = {
    "window-width": DEFAULT_WINDOW_WIDTH,
    "window-height": DEFAULT_WINDOW_HEIGHT,
    "jpeg-quality": DEFAULT_JPEG_QUALITY,
    "output-dpi": DEFAULT_OUTPUT_DPI,
    "auto-check-updates": DEFAULT_AUTO_CHECK_UPDATES,
}


class _FallbackSettings:
    """In-memory stand-in for Gio.Settings, used when the GSettings schema
    isn't installed (e.g. running the app directly during development,
    outside the AppImage/AppRun environment that sets
    GSETTINGS_SCHEMA_DIR). Nothing persists across runs in this mode, but
    the app still works."""

    def __init__(self):
        self._data = dict(_FALLBACK_DEFAULTS)

    def get_string(self, key):
        return self._data.get(key, "")

    def set_string(self, key, value):
        self._data[key] = value
        return True

    def get_int(self, key):
        return self._data.get(key, 0)

    def set_int(self, key, value):
        self._data[key] = value
        return True

    def get_boolean(self, key):
        return bool(self._data.get(key, False))

    def set_boolean(self, key, value):
        self._data[key] = bool(value)
        return True


def _backend_round_trips(backend) -> bool:
    """Some environments (no session D-Bus bus -- certain containers,
    minimal window managers, some remote sessions) have a GSettings
    schema available but a dconf backend whose writes silently don't
    take effect, even within the current process and even though
    set_*() reports success. Probing an existing key (rather than a
    throwaway one) once at startup means a broken backend gets routed to
    the in-memory fallback before anything is lost, so settings still
    behave correctly *within this session* instead of every change the
    user makes silently going nowhere."""
    probe_key = "window-width"
    original = backend.get_int(probe_key)
    probe_value = original + 1 if original < 99999 else original - 1
    backend.set_int(probe_key, probe_value)
    ok = backend.get_int(probe_key) == probe_value
    backend.set_int(probe_key, original)  # restore regardless of outcome
    return ok


def _make_backend():
    """Return a Gio.Settings bound to our schema if it's discoverable and
    actually works, otherwise an in-memory fallback. Gio.Settings.new()
    aborts the process on an unknown schema id rather than raising a
    catchable exception, so we check via SettingsSchemaSource first."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if source is not None and source.lookup(APP_ID, True) is not None:
            backend = Gio.Settings.new(APP_ID)
            if _backend_round_trips(backend):
                return backend
    except Exception:
        pass
    return _FallbackSettings()


class AppSettings:
    """Typed façade over the raw GSettings/_FallbackSettings backend.
    Use `settings.jpeg_quality` etc. instead of magic key strings."""

    def __init__(self):
        self._backend = _make_backend()

    @property
    def jpeg_quality(self):
        return self._backend.get_int("jpeg-quality") or DEFAULT_JPEG_QUALITY

    @jpeg_quality.setter
    def jpeg_quality(self, value):
        self._backend.set_int("jpeg-quality", int(value))

    @property
    def output_dpi(self):
        return self._backend.get_int("output-dpi") or DEFAULT_OUTPUT_DPI

    @output_dpi.setter
    def output_dpi(self, value):
        self._backend.set_int("output-dpi", int(value))

    @property
    def window_size(self):
        width = self._backend.get_int("window-width") or DEFAULT_WINDOW_WIDTH
        height = self._backend.get_int("window-height") or DEFAULT_WINDOW_HEIGHT
        return width, height

    def set_window_size(self, width, height):
        self._backend.set_int("window-width", width)
        self._backend.set_int("window-height", height)

    @property
    def last_add_folder(self):
        return self._backend.get_string("last-add-folder")

    @last_add_folder.setter
    def last_add_folder(self, value):
        self._backend.set_string("last-add-folder", value)

    @property
    def last_save_folder(self):
        return self._backend.get_string("last-save-folder")

    @last_save_folder.setter
    def last_save_folder(self, value):
        self._backend.set_string("last-save-folder", value)

    @property
    def auto_check_updates(self):
        return self._backend.get_boolean("auto-check-updates")

    @auto_check_updates.setter
    def auto_check_updates(self, value):
        self._backend.set_boolean("auto-check-updates", bool(value))

    @property
    def skip_update_version(self):
        return self._backend.get_string("skip-update-version")

    @skip_update_version.setter
    def skip_update_version(self, value):
        self._backend.set_string("skip-update-version", value)
