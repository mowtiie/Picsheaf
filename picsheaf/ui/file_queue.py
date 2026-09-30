"""FileQueueModel: wraps the Gtk.ListStore holding queued image files,
independent of how it's laid out on screen. Splitting this out from the
window means a future move off the deprecated Gtk.TreeView (to
Gtk.ColumnView, where GTK is heading) only touches window.py's widget
code, not the add/remove/reorder logic itself.
"""
import os

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf


class FileQueueModel:
    """Columns, addressed by the named constants below rather than magic
    numbers: a small thumbnail for list view, a larger one for grid view
    (both GdkPixbuf | None until generated), the display name, and the
    full path — the source of truth for both identity and page order."""

    COL_THUMB_SMALL = 0
    COL_THUMB_LARGE = 1
    COL_NAME = 2
    COL_PATH = 3

    def __init__(self):
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, GdkPixbuf.Pixbuf, str, str)

    def __len__(self):
        return len(self.store)

    def ordered_paths(self):
        """Full paths in current (possibly user-reordered) row order."""
        paths = []
        it = self.store.get_iter_first()
        while it is not None:
            paths.append(self.store.get_value(it, self.COL_PATH))
            it = self.store.iter_next(it)
        return paths

    def existing_paths(self):
        return set(self.ordered_paths())

    def add(self, path):
        self.store.append([None, None, os.path.basename(path), path])

    def find_iter_by_path(self, path):
        it = self.store.get_iter_first()
        while it is not None:
            if self.store.get_value(it, self.COL_PATH) == path:
                return it
            it = self.store.iter_next(it)
        return None

    def tree_path_for(self, path):
        """Gtk.TreePath for the row holding `path`, or None if not found."""
        it = self.find_iter_by_path(path)
        if it is None:
            return None
        return self.store.get_path(it)

    def set_thumbnails(self, path, small_pixbuf, large_pixbuf):
        it = self.find_iter_by_path(path)
        if it is None:
            return False
        if small_pixbuf is not None:
            self.store.set_value(it, self.COL_THUMB_SMALL, small_pixbuf)
        if large_pixbuf is not None:
            self.store.set_value(it, self.COL_THUMB_LARGE, large_pixbuf)
        return True

    def remove_at(self, tree_paths):
        """Remove rows at the given Gtk.TreePath list. Order-safe: removes
        highest row index first so earlier TreePaths stay valid."""
        for tp in sorted(tree_paths, key=lambda p: p.get_indices()[0], reverse=True):
            it = self.store.get_iter(tp)
            self.store.remove(it)

    def move(self, tree_path, direction):
        """direction: -1 to move a row up, +1 to move it down.
        Returns True if it moved, False if already at that boundary."""
        index = tree_path.get_indices()[0]
        target = index + direction
        if target < 0 or target >= len(self.store):
            return False
        it = self.store.get_iter(tree_path)
        target_it = self.store.iter_nth_child(None, target)
        self.store.swap(it, target_it)
        return True

    def clear(self):
        self.store.clear()

    def total_size_bytes(self):
        total = 0
        for path in self.ordered_paths():
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        return total
