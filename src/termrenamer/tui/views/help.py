"""Help: every key of the key table, where it works and what it does; Escape closes it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Static

from termrenamer.tui.keys import KEYS

VIEW_HINTS = "[b $accent]esc[/] Close  [b $accent]l[/] Logs  [b $accent]q[/] Quit"


def help_markup() -> str:
    """One line per key of the table: the key, where it works, what it does."""
    lines = [
        "[b]Keys[/b]",
        "",
        f"[$tr-dim]{'Key':<8}{'Where':<26}What it does[/]",
    ]
    for key in KEYS:
        lines.append(
            f"[b $accent]{escape(key.display):<8}[/][$tr-dim]{escape(key.where):<26}[/]"
            f"{escape(key.what)}"
        )
    return "\n".join(lines)


class HelpView(Screen[None]):
    """The key table, written out."""

    BINDINGS = [Binding("escape", "close", show=False)]

    DEFAULT_CSS = """
    HelpView VerticalScroll {
        height: 1fr;
        padding: 1 4;
    }
    HelpView #help-hints {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(help_markup(), id="help-body")
        yield Static(VIEW_HINTS, id="help-hints")

    def action_close(self) -> None:
        self.dismiss()
