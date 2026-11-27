"""The file and folder dialogs: textual_fspicker's, made safe for any folder.

Three parts of the package's dialogs are swapped for the app's own:

- The folder listing reads its entry styles on the app's thread only. The dialog lists
  its folder in a thread, and that thread reads the listing widget's component
  styles; the app empties and refills that table each time it restyles the widget
  (focus, hover, a theme), so a read from the thread in between would fail the worker
  and stop the app.
- A folder that cannot be listed (it is gone, or the disk refuses it) leaves the
  dialog open with an empty listing and says why, in place of ending the app. The
  ``..`` entry stays, so the person can go up.
- The current folder is shown as written: a folder named ``[$accent]x`` is never read
  as markup.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import cast

from rich.cells import cell_len
from textual import on, work
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual_fspicker import FileOpen, SelectDirectory
from textual_fspicker.parts import CurrentDirectory, DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntryStyling

_PACKAGE_LOAD = cast(
    "Callable[[DirectoryNavigation], None]",
    DirectoryNavigation._load.__wrapped__,  # type: ignore[attr-defined]  # noqa: SLF001
)
"""The package's listing of a folder, without its worker decorator."""


class _Listing(DirectoryNavigation):
    """The dialog's folder listing, reading its entry styles on the app's thread only,
    and saying why when its folder cannot be listed."""

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

    @work(exclusive=True, thread=True)
    def _load(self) -> None:
        try:
            _PACKAGE_LOAD(self)
        except OSError as exc:
            self._entries = []
            self.app.call_from_thread(self._unreadable, exc)

    class Unreadable(Message):
        """The folder could not be listed, for ``reason``.

        It reaches the dialog after the ``Changed`` that cleared the dialog's error line
        for this folder, as both travel the same way, so the reason stays shown."""

        def __init__(self, reason: str) -> None:
            super().__init__()
            self.reason = reason

    def _unreadable(self, error: OSError) -> None:
        """Show the folder as empty, and tell the dialog why."""
        self._repopulate_display()
        self.post_message(self.Unreadable(error.strerror or str(error)))

    def _repopulate_display(self) -> None:
        """List the entries read, with ``..`` first. When even ``..`` cannot be read (a
        folder inside one of another user), the listing is left with no entry; the
        dialog has said why already."""
        try:
            super()._repopulate_display()
        except OSError:
            self.clear_options()


class _Folder(CurrentDirectory):
    """The current folder, shown as written."""

    def _watch_current_directory(self) -> None:
        folder = "" if self.current_directory is None else str(self.current_directory)
        self.update(Content(_tail(folder, self.size.width)))


def _tail(text: str, width: int) -> str:
    """``text`` when it fits in ``width`` cells, else its end after "…", in ``width``
    cells at most; a wide character counts as two."""
    if not width or cell_len(text) <= width:
        return text
    kept, used = [], 1
    for character in reversed(text):
        used += cell_len(character)
        if used > width:
            break
        kept.append(character)
    return "…" + "".join(reversed(kept))


_CANNOT_READ = "This folder cannot be read: {reason}"
"""What the dialogs' error line says when a folder cannot be listed."""


def _say_unreadable(dialog: FileOpen | SelectDirectory, reason: str) -> None:
    """Say on ``dialog``'s error line, as plain text, why its folder cannot be listed."""
    text = Content(_CANNOT_READ.format(reason=reason))
    dialog._set_error(text)  # type: ignore[arg-type]  # noqa: SLF001


def _safe(widgets: Iterable[Widget], location: Path) -> Iterator[Widget]:
    """``widgets`` from a dialog's compose, its folder listing and its current folder
    swapped for the app's own."""
    for widget in widgets:
        if type(widget) is DirectoryNavigation:
            yield _Listing(location)
        elif type(widget) is CurrentDirectory:
            yield _Folder()
        else:
            yield widget


class FilePicker(FileOpen):
    """The file dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location

    def compose(self) -> Iterator[Widget]:
        return _safe(super().compose(), self._start)

    ERROR_PERMISSION_ERROR = _CANNOT_READ.format(reason="Permission denied")

    @on(_Listing.Unreadable)
    def _on_unreadable(self, event: _Listing.Unreadable) -> None:
        event.stop()
        _say_unreadable(self, event.reason)


class FolderPicker(SelectDirectory):
    """The folder dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location

    def compose(self) -> Iterator[Widget]:
        return _safe(super().compose(), self._start)

    ERROR_PERMISSION_ERROR = _CANNOT_READ.format(reason="Permission denied")

    @on(_Listing.Unreadable)
    def _on_unreadable(self, event: _Listing.Unreadable) -> None:
        event.stop()
        _say_unreadable(self, event.reason)
