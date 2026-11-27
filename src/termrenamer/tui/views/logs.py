"""Logs: every log line of the session and every message the screen gave; Escape closes it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import RichLog, Static

from termrenamer.tui.log_book import LogBook

VIEW_HINTS = "[b $accent]esc[/] Close  [b $accent]?[/] Help  [b $accent]q[/] Quit"


class LogsView(Screen[None]):
    """The log lines so far, and each new one as it comes."""

    BINDINGS = [Binding("escape", "close", show=False)]

    DEFAULT_CSS = """
    LogsView #logs-title {
        height: 2;
        padding: 0 2;
        text-style: bold;
        border-bottom: solid $tr-line;
    }
    LogsView RichLog {
        height: 1fr;
        background: $background;
        padding: 0 2;
        border: none;
    }
    LogsView #logs-hints {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    def __init__(self, book: LogBook) -> None:
        super().__init__()
        self._book = book
        self._last = 0

    def compose(self) -> ComposeResult:
        yield Static("Logs", id="logs-title")
        yield RichLog(id="log-lines", markup=False, highlight=False, wrap=True)
        yield Static(VIEW_HINTS, id="logs-hints")

    def on_mount(self) -> None:
        self.catch_up()

    def catch_up(self) -> None:
        """Write the book's lines this view has not written yet."""
        log = self.query_one(RichLog)
        for number, line in self._book.lines_after(self._last):
            log.write(line)
            self._last = number

    def action_close(self) -> None:
        self.dismiss()
