"""The footer: a message line, the current Stage's lines (such as a path), and the key hints."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.tui.keys import Key


class MessageKind(StrEnum):
    """The kind of a message: its colour on the message line and its level in the Logs."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DIM = "dim"

    @property
    def style(self) -> str:
        return {
            MessageKind.INFO: "$accent",
            MessageKind.WARNING: "$warning",
            MessageKind.ERROR: "$error",
            MessageKind.DIM: "$tr-dim",
        }[self]

    @property
    def level(self) -> int:
        return {
            MessageKind.WARNING: logging.WARNING,
            MessageKind.ERROR: logging.ERROR,
        }.get(self, logging.INFO)


def hints_markup(hints: Sequence[tuple[str, str]], width: int | None = None) -> str:
    """Each key and its label, as ``(key, label)`` pairs; as many as fit in ``width``."""
    out: list[str] = []
    used = 1
    for display, hint in hints:
        cells = len(display) + 1 + len(hint)
        if width is not None and used + cells > width - 1:
            break
        out.append(f"[b $accent]{escape(display)}[/] [$foreground]{escape(hint)}[/]")
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

    def show_message(self, text: str, kind: MessageKind = MessageKind.INFO) -> None:
        """Show ``text`` (plain) on the message line, coloured by ``kind``."""
        style = kind.style
        self.query_one("#message", Static).update(f"[{style}]{escape(text)}[/]" if text else "")

    def show_lines(self, lines: Sequence[str]) -> None:
        """Show the current Stage's lines (Textual markup), or hide the area when none."""
        area = self.query_one("#stage-lines", Static)
        area.update("\n".join(lines))
        area.display = bool(lines)

    def show_keys(self, keys: Sequence[Key]) -> None:
        hints = self.query_one("#key-hints", Static)
        pairs = [(key.display, key.hint) for key in keys]
        hints.update(hints_markup(pairs, self.size.width or self.app.size.width))
