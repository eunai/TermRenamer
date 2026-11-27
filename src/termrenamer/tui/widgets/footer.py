"""The footer: a message line, the current Stage's lines (such as a path), and the key hints."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.markup import escape
from textual.widgets import Static

from termrenamer.tui.keys import Key, drop_rank


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


def hints_markup(hints: Sequence[tuple[str, str]]) -> str:
    """Each key and its label, as ``(key, label)`` pairs."""
    return "  ".join(
        f"[b $accent]{escape(display)}[/] [$foreground]{escape(hint)}[/]" for display, hint in hints
    )


_GAP = 2
"""The cells between two hints."""


def fitting(shown: Sequence[Key], width: int) -> list[Key]:
    """The keys of ``shown`` whose hints fit in ``width`` cells, in their order.

    Hints are dropped by :func:`~termrenamer.tui.keys.drop_rank` until the rest fit;
    Help's stays even when it alone does not fit.
    """

    def cells(key: Key) -> int:
        return cell_len(key.display) + 1 + cell_len(key.hint)

    kept = list(shown)
    ranks = {id(key): drop_rank(key, position) for position, key in enumerate(shown)}
    droppable = sorted(
        (key for key in kept if ranks[id(key)] is not None), key=lambda k: ranks[id(k)] or 0
    )
    for key in droppable:
        if sum(cells(k) for k in kept) + _GAP * (len(kept) - 1) <= width:
            break
        kept.remove(key)
    return kept


_MESSAGE_ROWS = 2
"""The message line and the rule above it."""
_KEY_ROWS = 1
"""The key hints."""
_HINTS_PADDING = 2
"""The key hints' cells of padding, one each side."""

FOOTER_FIXED_ROWS = _MESSAGE_ROWS + _KEY_ROWS
"""The footer's rows besides the Stage's lines."""


class AppFooter(Vertical):
    """The message line, up to two lines from the current Stage, and the key hints."""

    DEFAULT_CSS = (
        """
    AppFooter {
        dock: bottom;
        height: auto;
    }
    AppFooter #message {
        padding: 0 2;
        border-top: solid $tr-line;
    }
    AppFooter #stage-lines {
        height: auto;
        padding: 0 2;
        background: $tr-footer;
    }
    AppFooter #key-hints {
        padding: 0 1;
        background: $panel;
    }
    """
        + f"""
    AppFooter #message {{
        height: {_MESSAGE_ROWS};
    }}
    AppFooter #key-hints {{
        height: {_KEY_ROWS};
    }}
    """
    )

    def compose(self) -> ComposeResult:
        yield Static(id="message")
        yield Static(id="stage-lines")
        yield Static(id="key-hints")

    def show_message(self, text: str, kind: MessageKind = MessageKind.INFO) -> None:
        """Show ``text`` (plain) on the message line, coloured by ``kind``."""
        style = kind.style
        shown = Content.from_markup(f"[{style}]$text[/]", text=text) if text else Content()
        self.query_one("#message", Static).update(shown)

    def show_lines(self, lines: Sequence[Content]) -> None:
        """Show the current Stage's lines, or hide the area when none."""
        area = self.query_one("#stage-lines", Static)
        area.update(Content("\n").join(lines))
        area.display = bool(lines)

    def show_keys(self, keys: Sequence[Key]) -> None:
        """Show the hints of ``keys`` that fit, by the key table's rule for a narrow footer."""
        hints = self.query_one("#key-hints", Static)
        width = (self.size.width or self.app.size.width) - _HINTS_PADDING
        hints.update(hints_markup([(key.display, key.hint) for key in fitting(keys, width)]))
