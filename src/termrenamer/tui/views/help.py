"""Help: every key of the key table, where it works and what it does, and the credits the
Providers ask for; Escape closes it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Static

from termrenamer.tui.keys import KEYS, VIEW_HINTS
from termrenamer.tui.widgets.footer import hints_markup

CREDITS = (
    "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    "Metadata provided by TheTVDB. Please consider adding missing information or "
    "subscribing. https://thetvdb.com/",
)
"""The credits TMDB and TheTVDB ask for where their data and Posters are shown."""


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
            f"{escape(key.help_text)}"
        )
    lines += ["", "[b]Credits[/b]", ""]
    lines += [escape(credit) for credit in CREDITS]
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
        yield Static(hints_markup(VIEW_HINTS["help"]), id="help-hints")

    def action_close(self) -> None:
        self.dismiss()
