"""About window builder."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from picsheaf import APP_ID, __version__

# Same author/org used throughout picsheaf_manager.sh (AppStream homepage,
# app ID) — update here and there together if this ever changes hands.
SOURCE_URL = "https://github.com/mowtiie/picsheaf"
AUTHOR_URL = "https://github.com/mowtiie"
ISSUES_URL = f"{SOURCE_URL}/issues"

USAGE_DETAILS = (
    "Files are converted in the order shown in the main window. Drag rows "
    "to reorder in list view, or drop image files anywhere in the list to "
    "add them."
)


def build_about_window(parent):
    about = Adw.AboutWindow(
        transient_for=parent,
        application_name="Picsheaf",
        application_icon=APP_ID,
        version=__version__,
        # Adjust to whatever license actually applies to your fork.
        license_type=Gtk.License.MIT_X11,
        comments=(
            "Convert images into a single PDF document, in the order you choose.\n\n"
            + USAGE_DETAILS
        ),
        issue_url=ISSUES_URL,
    )

    # Custom-labeled entries on the Credits page, in place of the default
    # "Created by" section. Each entry is Adw.AboutWindow's "Name URL"
    # format, rendered as a clickable link.
    about.add_credit_section("Source Code", [f"picsheaf {SOURCE_URL}"])
    about.add_credit_section("Author", [f"mowtiie {AUTHOR_URL}"])

    return about
