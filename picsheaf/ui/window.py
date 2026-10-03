"""Main application window.

This class owns widget layout and GTK-thread orchestration only. The
actual queue data lives in FileQueueModel, settings persistence lives in
AppSettings, and per-file conversion work lives in
picsheaf.conversion.convert_images_to_pdf — none of which import
each other's UI concerns.
"""
import os
import threading

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf, Pango

from picsheaf.settings import AppSettings
from picsheaf.conversion import convert_images_to_pdf
from picsheaf.thumbnails import generate_thumbnails_png_bytes
from picsheaf.image_formats import SUPPORTED_FORMATS, is_supported
from picsheaf.ui.file_queue import FileQueueModel
from picsheaf.ui.preferences import build_preferences_window

THUMB_SIZE_SMALL = 64   # list view
THUMB_SIZE_LARGE = 180  # grid view


def human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _pixbuf_to_picture_paintable(pixbuf):
    return Gdk.Texture.new_for_pixbuf(pixbuf)


class PicsheafWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = AppSettings()
        self.queue = FileQueueModel()
        self._view_mode = "list"

        self.set_title("Picsheaf")
        width, height = self.settings.window_size
        self.set_default_size(width, height)
        self.connect("close-request", self.on_close_request)

        # Header Bar
        header = Adw.HeaderBar()
        self.set_content(Gtk.Box(orientation=Gtk.Orientation.VERTICAL))
        self.get_content().append(header)

        # View mode switcher (list / grid), radio-style toggle buttons
        self.btn_view_list = Gtk.ToggleButton(icon_name="view-list-symbolic")
        self.btn_view_list.set_tooltip_text("List view")
        self.btn_view_grid = Gtk.ToggleButton(icon_name="view-grid-symbolic")
        self.btn_view_grid.set_tooltip_text("Grid view (larger thumbnails)")
        self.btn_view_grid.set_group(self.btn_view_list)
        self.btn_view_list.connect("toggled", self.on_view_mode_toggled)
        self.btn_view_grid.connect("toggled", self.on_view_mode_toggled)

        view_toggle_box = Gtk.Box()
        view_toggle_box.add_css_class("linked")
        view_toggle_box.append(self.btn_view_list)
        view_toggle_box.append(self.btn_view_grid)
        header.pack_start(view_toggle_box)

        menu_model = Gio.Menu()
        menu_model.append("Preferences", "win.preferences")
        menu_model.append("About Picsheaf", "app.about")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Menu")
        menu_button.set_popover(Gtk.PopoverMenu.new_from_model(menu_model))
        header.pack_end(menu_button)

        # Main Box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        self.get_content().append(main_box)

        # --- List view (Gtk.TreeView) ---
        self.tree_view = Gtk.TreeView(model=self.queue.store)
        self.tree_view.set_headers_visible(True)

        thumb_renderer = Gtk.CellRendererPixbuf()
        thumb_column = Gtk.TreeViewColumn("", thumb_renderer, pixbuf=FileQueueModel.COL_THUMB_SMALL)
        thumb_column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        thumb_column.set_fixed_width(THUMB_SIZE_SMALL + 16)
        self.tree_view.append_column(thumb_column)

        text_renderer = Gtk.CellRendererText()
        name_column = Gtk.TreeViewColumn("Selected Files (in page order)", text_renderer, text=FileQueueModel.COL_NAME)
        name_column.set_expand(True)
        self.tree_view.append_column(name_column)

        self.selection = self.tree_view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree_view.set_reorderable(True)

        # In SelectionMode.MULTIPLE, a plain click on an already-selected
        # row re-selects it rather than toggling it off — clicking the
        # sole selected row again does nothing by default, which reads as
        # "I can't deselect this." See the long comment above
        # _on_tree_view_pressed for how this is fixed (observe-then-correct,
        # not try to preempt GTK's own click handling).
        tree_click = Gtk.GestureClick()
        tree_click.set_button(Gdk.BUTTON_PRIMARY)
        tree_click.connect("pressed", self._on_tree_view_pressed)
        self.tree_view.add_controller(tree_click)

        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_vexpand(True)
        list_scroll.set_child(self.tree_view)

        # --- Grid view (Gtk.FlowBox), larger thumbnails ---
        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_valign(Gtk.Align.START)
        self.flow_box.set_max_children_per_line(8)
        self.flow_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.flow_box.set_homogeneous(True)
        self.flow_box.set_row_spacing(12)
        self.flow_box.set_column_spacing(12)
        self.flow_box.set_margin_top(12)
        self.flow_box.set_margin_bottom(12)
        self.flow_box.set_margin_start(12)
        self.flow_box.set_margin_end(12)

        # Same fix as the list view, applied to the grid (see the comment
        # above _on_tree_view_pressed): a plain click on the
        # already-sole-selected thumbnail now deselects it instead of
        # being a no-op.
        grid_click = Gtk.GestureClick()
        grid_click.set_button(Gdk.BUTTON_PRIMARY)
        grid_click.connect("pressed", self._on_flow_box_pressed)
        self.flow_box.add_controller(grid_click)

        grid_scroll = Gtk.ScrolledWindow()
        grid_scroll.set_vexpand(True)
        grid_scroll.set_child(self.flow_box)

        # Nested stack: which view (list/grid) is showing
        self.view_stack = Gtk.Stack()
        self.view_stack.add_named(list_scroll, "list")
        self.view_stack.add_named(grid_scroll, "grid")

        # Outer stack: empty-state placeholder vs. the view_stack above
        empty_page = Adw.StatusPage()
        empty_page.set_icon_name("image-x-generic-symbolic")
        empty_page.set_title("No Files Added")
        empty_page.set_description("Add images, or drop them here, to get started.")

        self.content_stack = Gtk.Stack()
        self.content_stack.set_vexpand(True)
        self.content_stack.add_named(empty_page, "empty")
        self.content_stack.add_named(self.view_stack, "content")
        main_box.append(self.content_stack)

        # Drag-and-drop import: accept files dropped anywhere in this area,
        # in either the empty state or either populated view.
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_drop)
        self.content_stack.add_controller(drop_target)

        # Keep the grid in sync with the underlying store automatically,
        # regardless of what changed it (add/remove/clear/drag-reorder/
        # move buttons/thumbnails arriving asynchronously) — one signal
        # hookup here replaces having to remember to refresh the grid at
        # every mutation call site.
        self.queue.store.connect("row-inserted", self._sync_grid_view)
        self.queue.store.connect("row-deleted", self._sync_grid_view)
        self.queue.store.connect("row-changed", self._sync_grid_view)
        self.queue.store.connect("rows-reordered", self._sync_grid_view)

        # Live summary of what's queued (count + total source size)
        self.size_label = Gtk.Label(label="No files queued.")
        self.size_label.set_xalign(0)
        self.size_label.add_css_class("dim-label")
        main_box.append(self.size_label)

        # File Button Controls Box (add / remove / reorder / clear)
        file_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_box.append(file_btn_box)

        self.btn_add = Gtk.Button(label="Add Image Files")
        self.btn_add.connect("clicked", self.on_add_files)
        file_btn_box.append(self.btn_add)

        self.btn_remove = Gtk.Button(label="Remove Selected")
        self.btn_remove.connect("clicked", self.on_remove_selected)
        file_btn_box.append(self.btn_remove)

        self.btn_move_up = Gtk.Button(icon_name="go-up-symbolic")
        self.btn_move_up.set_tooltip_text("Move selected file up (list view only)")
        self.btn_move_up.connect("clicked", self.on_move_up)
        file_btn_box.append(self.btn_move_up)

        self.btn_move_down = Gtk.Button(icon_name="go-down-symbolic")
        self.btn_move_down.set_tooltip_text("Move selected file down (list view only)")
        self.btn_move_down.connect("clicked", self.on_move_down)
        file_btn_box.append(self.btn_move_down)

        self.btn_clear = Gtk.Button(label="Clear All")
        self.btn_clear.connect("clicked", self.on_clear_files)
        file_btn_box.append(self.btn_clear)

        # Convert Controls Box
        convert_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        main_box.append(convert_btn_box)

        self.btn_convert = Gtk.Button(label="Convert to PDF")
        self.btn_convert.add_css_class("suggested-action")
        self.btn_convert.connect("clicked", self.on_convert)
        convert_btn_box.append(self.btn_convert)

        self.btn_cancel = Gtk.Button(label="Cancel")
        self.btn_cancel.add_css_class("destructive-action")
        self.btn_cancel.connect("clicked", self.on_cancel)
        self.btn_cancel.set_visible(False)
        convert_btn_box.append(self.btn_cancel)

        # Progress bar (hidden until a conversion is running)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_visible(False)
        main_box.append(self.progress_bar)

        self.status_label = Gtk.Label(label="Select files to get started.")
        main_box.append(self.status_label)

        self._all_controls = [
            self.btn_add, self.btn_remove, self.btn_move_up,
            self.btn_move_down, self.btn_clear, self.btn_convert,
        ]
        self._cancel_event = threading.Event()

        # Window-scoped actions (drive both menu items and keyboard shortcuts)
        self._add_window_action("add-files", self.on_add_files)
        self._add_window_action("convert", self.on_convert)
        self._add_window_action("remove-selected", self.on_remove_selected)
        self._add_window_action("preferences", self.on_preferences)

        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.add-files", ["<Control>o"])
            app.set_accels_for_action("win.convert", ["<Control>s"])
            app.set_accels_for_action("win.remove-selected", ["Delete"])

        self.btn_view_list.set_active(True)  # fires on_view_mode_toggled once
        self.refresh_list_ui()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _add_window_action(self, name, handler):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", handler)
        self.add_action(action)

    def update_count_status(self, prefix=""):
        count = len(self.queue)
        suffix = "file" if count == 1 else "files"
        self.status_label.set_text(f"{prefix}{count} {suffix} queued.")

    def refresh_list_ui(self):
        """Call after any add/remove/clear: switches between the empty
        state and the file views, and refreshes the size summary line."""
        count = len(self.queue)
        self.content_stack.set_visible_child_name("content" if count else "empty")

        if count == 0:
            self.size_label.set_text("No files queued.")
            return

        total = self.queue.total_size_bytes()
        self.size_label.set_text(
            f"{count} file{'s' if count != 1 else ''} queued \u2022 {human_size(total)} of source images "
            "(final PDF size depends on quality/DPI settings)"
        )

    def set_controls_sensitive(self, sensitive):
        for widget in self._all_controls:
            widget.set_sensitive(sensitive)
        # Reordering only makes sense in list view; keep them off in grid
        # view even when the rest of the controls are re-enabled.
        if sensitive and self._view_mode == "grid":
            self.btn_move_up.set_sensitive(False)
            self.btn_move_down.set_sensitive(False)

    def on_close_request(self, *args):
        # Persist window size for next launch; harmless no-op under the
        # in-memory fallback settings.
        try:
            width, height = self.get_width(), self.get_height()
            if width > 0 and height > 0:
                self.settings.set_window_size(width, height)
        except Exception:
            pass
        return False  # allow the window to close normally

    # ------------------------------------------------------------------
    # View mode (list / grid)
    # ------------------------------------------------------------------
    def on_view_mode_toggled(self, button):
        if not button.get_active():
            return
        if button is self.btn_view_grid:
            self._view_mode = "grid"
            self.view_stack.set_visible_child_name("grid")
            self.btn_move_up.set_sensitive(False)
            self.btn_move_down.set_sensitive(False)
        else:
            self._view_mode = "list"
            self.view_stack.set_visible_child_name("list")
            self.btn_move_up.set_sensitive(True)
            self.btn_move_down.set_sensitive(True)

    def _sync_grid_view(self, *args):
        """Full rebuild of the FlowBox contents from the store. Simple and
        correct; the file counts this app deals with (tens, not
        thousands) make a full rebuild on every change cheap enough that
        incremental diffing isn't worth the complexity."""
        child = self.flow_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.flow_box.remove(child)
            child = next_child

        it = self.queue.store.get_iter_first()
        while it is not None:
            large_pixbuf = self.queue.store.get_value(it, FileQueueModel.COL_THUMB_LARGE)
            name = self.queue.store.get_value(it, FileQueueModel.COL_NAME)
            path = self.queue.store.get_value(it, FileQueueModel.COL_PATH)

            cell_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            picture = Gtk.Picture()
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_size_request(THUMB_SIZE_LARGE, THUMB_SIZE_LARGE)
            if large_pixbuf is not None:
                picture.set_paintable(_pixbuf_to_picture_paintable(large_pixbuf))
            cell_box.append(picture)

            label = Gtk.Label(label=name)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_max_width_chars(20)
            cell_box.append(label)

            flow_child = Gtk.FlowBoxChild()
            flow_child.set_child(cell_box)
            flow_child.queue_path = path
            self.flow_box.append(flow_child)

            it = self.queue.store.iter_next(it)
        return False

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    def on_preferences(self, action, param=None):
        window = build_preferences_window(self, self.settings)
        window.present()

    # ------------------------------------------------------------------
    # Add files (file picker + drag-and-drop) with async thumbnails
    # ------------------------------------------------------------------
    def add_paths(self, paths):
        """Add a list of candidate file paths, skipping duplicates and
        anything in an unsupported format. Rows appear immediately with a
        placeholder icon; real thumbnails are generated in the background
        so adding many/large files never freezes the UI."""
        already_have = self.queue.existing_paths()
        new_paths = []
        for path in paths:
            if not path or path in already_have:
                continue
            if not is_supported(path):
                continue
            self.queue.add(path)
            already_have.add(path)
            new_paths.append(path)

        if new_paths:
            self.update_count_status(prefix=f"Added {len(new_paths)} file(s) — ")
            threading.Thread(
                target=self._generate_thumbnails,
                args=(new_paths,),
                daemon=True
            ).start()
        elif paths:
            self.status_label.set_text("No new supported image files to add (duplicates or unsupported type were skipped).")

        self.refresh_list_ui()

    def _generate_thumbnails(self, paths):
        for path in paths:
            small_pixbuf = None
            large_pixbuf = None
            try:
                sizes = generate_thumbnails_png_bytes(path, [THUMB_SIZE_SMALL, THUMB_SIZE_LARGE])
                small_pixbuf = self._png_bytes_to_pixbuf(sizes[THUMB_SIZE_SMALL])
                large_pixbuf = self._png_bytes_to_pixbuf(sizes[THUMB_SIZE_LARGE])
            except Exception:
                pass
            GLib.idle_add(self._apply_thumbnails, path, small_pixbuf, large_pixbuf)

    @staticmethod
    def _png_bytes_to_pixbuf(data):
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()

    def _apply_thumbnails(self, path, small_pixbuf, large_pixbuf):
        self.queue.set_thumbnails(path, small_pixbuf, large_pixbuf)
        return False

    def on_add_files(self, button, param=None):
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Image Files")

        filter_images = Gtk.FileFilter()
        filter_images.set_name("Image Files")
        for ext, mime in SUPPORTED_FORMATS.items():
            filter_images.add_mime_type(mime)
            filter_images.add_pattern(f"*{ext}")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_images)
        dialog.set_filters(filters)

        last_folder = self.settings.last_add_folder
        if last_folder and os.path.isdir(last_folder):
            try:
                dialog.set_initial_folder(Gio.File.new_for_path(last_folder))
            except Exception:
                pass

        dialog.open_multiple(self, None, self.on_files_selected)

    def on_files_selected(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
            paths = [f.get_path() for f in files]
            self.add_paths(paths)
            if paths:
                folder = os.path.dirname(paths[0])
                if folder:
                    self.settings.last_add_folder = folder
        except Exception:
            pass

    def on_drop(self, drop_target, value, x, y):
        try:
            files = value.get_files()  # Gdk.FileList -> list[Gio.File]
            self.add_paths([f.get_path() for f in files])
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Click-to-deselect (see the comments where these controllers are
    # attached, next to tree_click/grid_click, for why this exists)
    #
    # This does NOT try to preempt GTK's own click-to-select handling —
    # e.g. by claiming the press event in a CAPTURE-phase gesture — since
    # that depends on assumptions about event-propagation/claim ordering
    # between our controller and the widget's own built-in selection
    # gesture that aren't guaranteed by the public API. Instead: let the
    # click go through completely normally, and correct the result
    # afterward. "pressed" fires synchronously alongside every other
    # controller watching the same event, including the widget's own
    # click-to-select logic, so by the time our handler runs we can't yet
    # tell what GTK is about to do with it — but scheduling our check via
    # GLib.idle_add defers it to the next main-loop iteration, by which
    # point that synchronous dispatch (GTK's default handling included)
    # has already finished. If the outcome is still "that one item I
    # clicked is the sole selection," this click was a no-op under GTK's
    # default behavior, so we toggle it off.
    # ------------------------------------------------------------------
    @staticmethod
    def _click_has_modifier(gesture):
        state = gesture.get_current_event_state()
        return bool(state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))

    def _on_tree_view_pressed(self, gesture, n_press, x, y):
        if n_press != 1 or self._click_has_modifier(gesture):
            return
        hit = self.tree_view.get_path_at_pos(int(x), int(y))
        if hit is None:
            return
        path = hit[0]
        if not self.selection.path_is_selected(path):
            return
        _, selected_paths = self.selection.get_selected_rows()
        if len(selected_paths) == 1 and selected_paths[0].compare(path) == 0:
            GLib.idle_add(self._finish_tree_toggle, path)

    def _finish_tree_toggle(self, path):
        _, selected_paths = self.selection.get_selected_rows()
        if len(selected_paths) == 1 and selected_paths[0].compare(path) == 0:
            self.selection.unselect_path(path)
        return False

    def _on_flow_box_pressed(self, gesture, n_press, x, y):
        if n_press != 1 or self._click_has_modifier(gesture):
            return
        child = self.flow_box.get_child_at_pos(int(x), int(y))
        if child is None or not child.is_selected():
            return
        selected = self.flow_box.get_selected_children()
        if len(selected) == 1 and selected[0] == child:
            GLib.idle_add(self._finish_flow_toggle, child)

    def _finish_flow_toggle(self, child):
        selected = self.flow_box.get_selected_children()
        if len(selected) == 1 and selected[0] == child:
            self.flow_box.unselect_child(child)
        return False

    # ------------------------------------------------------------------
    # Remove / reorder / clear
    # ------------------------------------------------------------------
    def _selected_tree_paths(self):
        """Selected rows as Gtk.TreePath, from whichever view is active."""
        if self._view_mode == "grid":
            paths = []
            for child in self.flow_box.get_selected_children():
                tp = self.queue.tree_path_for(child.queue_path)
                if tp is not None:
                    paths.append(tp)
            return paths
        _, paths = self.selection.get_selected_rows()
        return paths

    def on_remove_selected(self, button, param=None):
        tree_paths = self._selected_tree_paths()
        if not tree_paths:
            self.status_label.set_text("Select one or more files to remove first.")
            return
        self.queue.remove_at(tree_paths)
        self.update_count_status(prefix=f"Removed {len(tree_paths)} file(s) — ")
        self.refresh_list_ui()

    def on_move_up(self, button):
        model, paths = self.selection.get_selected_rows()
        if len(paths) != 1:
            self.status_label.set_text("Select exactly one file to move.")
            return
        self.queue.move(paths[0], -1)

    def on_move_down(self, button):
        model, paths = self.selection.get_selected_rows()
        if len(paths) != 1:
            self.status_label.set_text("Select exactly one file to move.")
            return
        self.queue.move(paths[0], 1)

    def on_clear_files(self, button):
        self.queue.clear()
        self.status_label.set_text("Cleared file list.")
        self.refresh_list_ui()

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def on_convert(self, button, param=None):
        if len(self.queue) == 0:
            self.status_label.set_text("Please add at least one image file!")
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Save Combined PDF")
        dialog.set_initial_name("output.pdf")

        last_folder = self.settings.last_save_folder
        if last_folder and os.path.isdir(last_folder):
            try:
                dialog.set_initial_folder(Gio.File.new_for_path(last_folder))
            except Exception:
                pass

        dialog.save(self, None, self.on_save_location_selected)

    def on_save_location_selected(self, dialog, result):
        try:
            target_file = dialog.save_finish(result)
            output_pdf = target_file.get_path()

            folder = os.path.dirname(output_pdf)
            if folder:
                self.settings.last_save_folder = folder

            ordered_files = self.queue.ordered_paths()
            quality = self.settings.jpeg_quality
            dpi = self.settings.output_dpi

            self._cancel_event = threading.Event()
            self.set_controls_sensitive(False)
            self.btn_cancel.set_visible(True)
            self.btn_cancel.set_sensitive(True)
            self.progress_bar.set_fraction(0.0)
            self.progress_bar.set_text(f"0 / {len(ordered_files)}")
            self.progress_bar.set_visible(True)
            self.status_label.set_text("Converting images to PDF...")

            self._start_conversion_thread(ordered_files, output_pdf, quality, dpi)
        except Exception:
            pass

    def _start_conversion_thread(self, ordered_files, output_pdf, quality, dpi):
        """Runs the pure conversion function on a background thread and
        marshals its callbacks/result back onto the GTK main loop."""

        def progress_cb(done, total):
            GLib.idle_add(self._update_progress, done, total)

        def should_cancel():
            return self._cancel_event.is_set()

        def run():
            result = convert_images_to_pdf(
                ordered_files, output_pdf, quality, dpi,
                progress_cb=progress_cb, should_cancel=should_cancel,
            )
            GLib.idle_add(
                self.on_conversion_finished,
                result.success, result.message, result.skipped or None
            )

        threading.Thread(target=run, daemon=True).start()

    def on_cancel(self, button):
        self._cancel_event.set()
        self.btn_cancel.set_sensitive(False)
        self.status_label.set_text("Cancelling...")

    def _update_progress(self, done, total):
        self.progress_bar.set_fraction(done / total if total else 0.0)
        self.progress_bar.set_text(f"{done} / {total}")
        return False

    def on_conversion_finished(self, success, message, skipped):
        self.progress_bar.set_visible(False)
        self.btn_cancel.set_visible(False)
        self.set_controls_sensitive(True)
        self.status_label.set_text(message)
        if skipped:
            self.show_skipped_dialog(skipped)
        return False

    def show_skipped_dialog(self, skipped):
        lines = "\n".join(f"\u2022 {name}: {reason}" for name, reason in skipped)
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"{len(skipped)} file(s) were skipped",
            body=lines,
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()
