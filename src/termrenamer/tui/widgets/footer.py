"""The footer: a message line, the current Stage's lines (such as a path), and the key hints."""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.tui.keys import Key

MESSAGE_STYLES = {"info": "$accent", "warning": "$warning", "error": "$error", "dim": "$tr-dim"}
"""The colour of a message line, by its kind."""


def hints_markup(keys: Sequence[Key], width: int) -> str:
    """Each key and its hint, as many as fit in ``width`` cells."""
    out: list[str] = []
    used = 1
    for key in keys:
        cells = len(key.display) + 1 + len(key.hint)
        if used + cells > width - 1:
            break
        out.append(f"[b $accent]{escape(key.display)}[/] [$foreground]{escape(key.hint)}[/]")
        used += cells + 2
    return "  ".join(out)


class AppFooter(Vertical):
    """The message line, up to two lines from the current Stage, and the key hints."""

    DEFAULT_CSS = """
    AppFooter {
        dock: bottom;
        height: auto;
    }
    AppFooter #message {
        height: 2;
        padding: 0 2;
        border-top: solid $tr-line;
    }
    AppFooter #stage-lines {
        height: auto;
        padding: 0 2;
        background: $tr-footer;
    }
    AppFooter #key-hints {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="message")
        yield Static(id="stage-lines")
        yield Static(id="key-hints")

    def show_message(self, text: str, kind: str = "info") -> None:
        """Show ``text`` (plain) on the message line, coloured by ``kind``."""
        style = MESSAGE_STYLES.get(kind, "$accent")
        self.query_one("#message", Static).update(f"[{style}]{escape(text)}[/]" if text else "")

    def show_lines(self, lines: Sequence[str]) -> None:
        """Show the current Stage's lines (Textual markup), or hide the area when none."""
        area = self.query_one("#stage-lines", Static)
        area.update("\n".join(lines))
        area.display = bool(lines)

    def show_keys(self, keys: Sequence[Key]) -> None:
        hints = self.query_one("#key-hints", Static)
        hints.update(hints_markup(keys, self.size.width or self.app.size.width))
