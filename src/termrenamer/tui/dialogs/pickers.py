"""The file and folder dialogs: textual_fspicker's, made safe for any folder.

Four parts of the package's dialogs are swapped for the app's own:

- The folder listing reads its entry styles on the app's thread only. The dialog lists
  its folder in a thread, and that thread reads the listing widget's component
  styles; the app empties and refills that table each time it restyles the widget
  (focus, hover, a theme), so a read from the thread in between would fail the worker
  and stop the app.
- A folder that cannot be listed or entered (it is gone, the disk refuses to list it,
  or its names can be read but not looked at) leaves the dialog open with an empty
  listing and says why, in place of ending the app; backspace goes up.
- The file dialog's name field suggests a path as the person types; a path the disk
  cannot answer for gets no suggestion, and Enter on it says why on the error line,
  in place of ending the app.
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
from textual.widgets import Button, Input
from textual_fspicker import FileOpen, SelectDirectory
from textual_fspicker.file_dialog import BaseFileDialog
from textual_fspicker.parts import CurrentDirectory, DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntryStyling
from textual_fspicker.suggest_path import SuggestPath

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
        """List the entries read, with ``..`` first. When even ``..`` cannot be looked at
        (the folder can be listed but not entered, or not at all), the listing is left
        with no entry and the dialog says why."""
        try:
            super()._repopulate_display()
        except OSError as exc:
            self.clear_options()
            self.post_message(self.Unreadable(exc.strerror or str(exc)))


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


_CANNOT_USE = "This path cannot be used: {reason}"
"""What the file dialog's error line says when the disk cannot tell what a typed path
is."""

_CANNOT_READ = "This folder cannot be read: {reason}"
"""What the dialogs' error line says when a folder cannot be listed."""


def _say_unreadable(dialog: FileOpen | SelectDirectory, reason: str) -> None:
    """Say on ``dialog``'s error line, as plain text, why its folder cannot be listed."""
    _say(dialog, _CANNOT_READ.format(reason=reason))


def _say(dialog: FileOpen | SelectDirectory, text: str) -> None:
    """Show ``text`` on ``dialog``'s error line, as plain text."""
    dialog._set_error(Content(text))  # type: ignore[arg-type]  # noqa: SLF001


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


class _Suggestions(SuggestPath):
    """The package's path suggestions, with none for a path the disk cannot answer for
    (a folder that refuses to be looked in, a name too long)."""

    async def get_suggestion(self, value: str) -> str | None:
        try:
            return await super().get_suggestion(value)
        except OSError:
            return None


class FilePicker(FileOpen):
    """The file dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location
        self._suggest_path = _Suggestions()

    def compose(self) -> Iterator[Widget]:
        return _safe(super().compose(), self._start)

    ERROR_PERMISSION_ERROR = _CANNOT_READ.format(reason="Permission denied")

    @on(_Listing.Unreadable)
    def _on_unreadable(self, event: _Listing.Unreadable) -> None:
        event.stop()
        _say_unreadable(self, event.reason)

    @on(Input.Submitted)
    @on(Button.Pressed, "#select")
    def _confirm_or_say_why(self, event: Input.Submitted | Button.Pressed) -> None:
        """Run the package's confirm in place of its own handler; when the disk cannot
        tell what the typed path is (a name too long), say so and keep the dialog."""
        event.prevent_default()
        try:
            BaseFileDialog._confirm_file(self, event)  # noqa: SLF001
        except OSError as exc:
            _say(self, _CANNOT_USE.format(reason=exc.strerror or str(exc)))


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
