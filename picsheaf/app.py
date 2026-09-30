"""Application entrypoint: Adw.Application subclass + app-level actions."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio

from picsheaf import APP_ID
from picsheaf.ui.window import PicsheafWindow
from picsheaf.ui.about import build_about_window


class PicsheafApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about)
        self.add_action(about_action)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = PicsheafWindow(application=self)
        win.present()

    def on_about(self, action, param):
        about = build_about_window(self.props.active_window)
        about.present()
