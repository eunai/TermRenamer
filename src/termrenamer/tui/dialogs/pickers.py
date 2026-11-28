"""The file and folder dialogs: textual_fspicker's, made safe for any folder.

Parts of the package's dialogs are swapped for, or wrapped by, the app's own:

- The folder listing reads its entry styles on the app's thread only. The dialog lists
  its folder in a thread, and that thread reads the listing widget's component
  styles; the app empties and refills that table each time it restyles the widget
  (focus, hover, a theme), so a read from the thread in between would fail the worker
  and stop the app.
- A folder that cannot be listed or entered (it is gone, the disk refuses to list it,
  or its names can be read but not looked at) leaves the dialog open with an empty
  listing and says why, in place of ending the app; backspace goes up. A listing is
  shown only while its folder is the one the dialog is on: one the person left before
  it ended changes nothing.
- Enter (or a click) on a listed entry that the disk cannot say is a folder or a file
  keeps the dialog on its folder and says why.
- The file dialog's name field suggests a path as the person types; a path the disk
  cannot answer for gets no suggestion, and Enter on it says why on the error line,
  in place of ending the app.
- The current folder is shown as written: a folder named ``[$accent]x`` is never read
  as markup.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from pathlib import Path

from rich.cells import cell_len
from textual import on, work
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, OptionList
from textual.worker import Worker, get_current_worker
from textual_fspicker import FileOpen, SelectDirectory
from textual_fspicker.file_dialog import BaseFileDialog
from textual_fspicker.parts import CurrentDirectory, DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntry, DirectoryEntryStyling
from textual_fspicker.safe_tests import is_dir, is_file
from textual_fspicker.suggest_path import SuggestPath

from termrenamer.tui.words import NO_NUL, NUL, error_reason


class _Listing(DirectoryNavigation):
    """The dialog's folder listing, reading its entry styles on the app's thread only,
    showing only the listing of the folder it is on, and saying why when the disk
    fails it."""

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
        """List the current folder off the app's thread, as the package does, into a
        list of this listing's own; the app's thread shows it if it is still wanted."""
        worker = get_current_worker()
        location = self._location
        styles = self._styles
        entries: list[DirectoryEntry] = []
        reason: str | None = None
        try:
            for entry in location.iterdir():
                if worker.is_cancelled:
                    return
                if is_dir(entry) or (is_file(entry) and self.show_files):
                    entries.append(DirectoryEntry(location / entry.name, styles))
        except OSError as exc:  # gone, refused, or the disk failed
            entries, reason = [], error_reason(exc)
        self.app.call_from_thread(self._listed, worker, location, entries, reason)

    def _listed(
        self,
        worker: Worker[None],
        location: Path,
        entries: list[DirectoryEntry],
        reason: str | None,
    ) -> None:
        """Show ``entries``, read by ``worker`` from ``location``, unless the person
        has moved on since: a later listing was started, or the folder changed."""
        if worker.is_cancelled or location != self._location:
            return
        self._entries = entries
        self._repopulate_display()
        if reason is not None:
            self.post_message(self.Says(_CANNOT_READ.format(reason=reason)))

    class Says(Message):
        """The line the dialog's error line should show, as plain text.

        A folder's reason reaches the dialog after the ``Changed`` that cleared the
        error line for that folder, as both travel the same way, so the reason stays
        shown."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def _repopulate_display(self) -> None:
        """List the entries read, with ``..`` first. When even ``..`` cannot be looked at
        (the folder can be listed but not entered, or not at all), the listing is left
        with no entry and the dialog says why."""
        try:
            super()._repopulate_display()
        except OSError as exc:
            self.clear_options()
            self.post_message(self.Says(_CANNOT_READ.format(reason=error_reason(exc))))

    def _on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on an entry: the package's going in or choosing, in place of its own
        handler; when the disk cannot say what the entry is, the dialog says why and
        stays on its folder."""
        event.prevent_default()
        try:
            DirectoryNavigation._on_option_list_option_selected(self, event)  # noqa: SLF001
        except OSError as exc:
            self.post_message(self.Says(_CANNOT_USE.format(reason=error_reason(exc))))


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
    (a folder that refuses to be looked in, a name too long) or that no path can be
    (one holding a NUL character, or text the file system cannot encode)."""

    async def get_suggestion(self, value: str) -> str | None:
        try:
            return await super().get_suggestion(value)
        except (OSError, ValueError):
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

    @on(_Listing.Says)
    def _on_says(self, event: _Listing.Says) -> None:
        event.stop()
        _say(self, event.text)

    @on(Input.Submitted)
    @on(Button.Pressed, "#select")
    def _confirm_or_say_why(self, event: Input.Submitted | Button.Pressed) -> None:
        """Run the package's confirm in place of its own handler; when the disk cannot
        tell what the typed path is (a name too long) or no path can be it (one holding
        a NUL character), say so and keep the dialog."""
        event.prevent_default()
        if NUL in self.query_one(Input).value:
            _say(self, _CANNOT_USE.format(reason=NO_NUL))
            return
        try:
            BaseFileDialog._confirm_file(self, event)  # noqa: SLF001
        except (OSError, ValueError) as exc:
            _say(self, _CANNOT_USE.format(reason=error_reason(exc)))


class FolderPicker(SelectDirectory):
    """The folder dialog, opening at ``location``."""

    def __init__(self, location: Path) -> None:
        super().__init__(str(location))
        self._start = location

    def compose(self) -> Iterator[Widget]:
        return _safe(super().compose(), self._start)

    ERROR_PERMISSION_ERROR = _CANNOT_READ.format(reason="Permission denied")

    @on(_Listing.Says)
    def _on_says(self, event: _Listing.Says) -> None:
        event.stop()
        _say(self, event.text)
