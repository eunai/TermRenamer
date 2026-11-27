"""The file and folder dialogs: textual_fspicker's, with a folder listing safe from its thread.

The dialog lists its folder in a thread, and that thread reads the listing widget's
component styles. The app empties and refills that table each time it restyles the
widget (focus, hover, a theme), so a read from the thread in between fails the worker
and stops the app. Here the listing hands each such read to the app's thread.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from pathlib import Path

from textual.widget import Widget
from textual_fspicker import FileOpen, SelectDirectory
from textual_fspicker.parts import DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntryStyling


class _Listing(DirectoryNavigation):
    """The dialog's folder listing, reading its entry styles on the app's thread only."""

    def __init__(self, location: Path) -> None:
        super().__init__(location)
        # Built during the dialog's compose, so on the app's thread.
        self._app_thread = threading.get_ident()

    @property
    def _styles(self) -> DirectoryEntryStyling:
        def read() -> DirectoryEntryStyling:
            return super(_Listing, self)._styles

        if threading.get_ident() == self._app_thread:
            return read()
        return self.app.call_from_thread(read)


def _with_safe_listing(widgets: Iterable[Widget], location: Path) -> Iterator[Widget]:
    """``widgets`` from a dialog's compose, its folder listing swapped for ``_Listing``."""
    for widget in widgets:
        yield _Listing(location) if type(widget) is DirectoryNavigation else widget


class FilePicker(FileOpen):
    """The file dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location

    def compose(self) -> Iterator[Widget]:
        return _with_safe_listing(super().compose(), self._start)


class FolderPicker(SelectDirectory):
    """The folder dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location

    def compose(self) -> Iterator[Widget]:
        return _with_safe_listing(super().compose(), self._start)
