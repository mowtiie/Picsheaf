"""Preferences window: JPEG quality / output DPI, backed by AppSettings."""
import gi
gi.require_version('Adw', '1')
from gi.repository import Adw


def build_preferences_window(parent, settings):
    """Build (but don't present) the Preferences window for `settings`,
    transient for `parent`. Each row writes back to `settings`
    immediately as the user adjusts it."""
    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(title="Conversion")
    page.add(group)

    quality_row = Adw.SpinRow.new_with_range(1, 100, 1)
    quality_row.set_title("JPEG Quality")
    quality_row.set_subtitle("Higher values give larger, higher-quality intermediate images (default 90)")
    quality_row.set_value(settings.jpeg_quality)
    quality_row.connect(
        "notify::value",
        lambda row, _: setattr(settings, "jpeg_quality", int(row.get_value()))
    )
    group.add(quality_row)

    dpi_row = Adw.SpinRow.new_with_range(72, 600, 1)
    dpi_row.set_title("Output DPI")
    dpi_row.set_subtitle("Controls the physical page size embedded in the PDF (default 150)")
    dpi_row.set_value(settings.output_dpi)
    dpi_row.connect(
        "notify::value",
        lambda row, _: setattr(settings, "output_dpi", int(row.get_value()))
    )
    group.add(dpi_row)

    window = Adw.PreferencesWindow(transient_for=parent)
    window.add(page)
    return window
