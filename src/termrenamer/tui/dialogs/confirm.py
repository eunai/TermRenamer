"""A yes-or-no confirm: a titled box of lines over the Title list, with two buttons.

It returns ``True`` for ``y`` and ``False`` for ``n`` or Escape; a subclass may add
``enter`` for yes. It sits right of where the Poster panel goes, and keeps clear of the
panel while it shows. However many lines it holds, both buttons stay on screen: the
lines scroll above them, with the arrows, Page Up and Page Down, Home and End, or the
mouse wheel.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Static

from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.poster_panel import keep_clear_of_posters

_CHROME_ROWS = 6
"""The dialog's rows besides its lines: the border above and below, the gap above and
below the lines, the buttons and the gap under them."""


class _Lines(VerticalScroll, can_focus=False):
    """The confirm's lines, scrolling when they are taller than the screen allows. It
    never takes focus, so ``y``, ``n`` and ``enter`` always reach the dialog."""


class ConfirmDialog(ModalScreen[bool]):
    """``title`` over ``lines``, then the yes button (``y``) and the no button (``n``).

    ``lines`` is a :class:`~textual.content.Content`, so a caller decides what is markup:
    a path or a file name in it is never read as markup unless the caller made it so.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
        Binding("up", "scroll_lines('up')", show=False),
        Binding("down", "scroll_lines('down')", show=False),
        Binding("pageup", "scroll_lines('page_up')", show=False),
        Binding("pagedown", "scroll_lines('page_down')", show=False),
        Binding("home", "scroll_lines('home')", show=False),
        Binding("end", "scroll_lines('end')", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: right middle;
        background: $background 60%;
    }
    ConfirmDialog #confirm-dialog {
        width: 62;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        margin-right: 12;
        padding: 0 2;
        border: round $accent;
        border-title-color: $foreground;
        border-title-style: bold;
        background: $tr-dialog;
    }
    ConfirmDialog #confirm-scroll {
        height: auto;
        margin: 1 0 1 0;
        scrollbar-size-vertical: 1;
    }
    ConfirmDialog #confirm-lines {
        height: auto;
    }
    ConfirmDialog .buttons {
        height: 1;
        margin-bottom: 1;
    }
    ConfirmDialog .buttons ActionButton {
        margin: 0 2 0 0;
    }
    """

    def __init__(self, title: str, lines: Content, yes: str, no: str) -> None:
        super().__init__()
        self._title = title
        self._lines = lines
        self._yes = yes
        self._no = no

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            with _Lines(id="confirm-scroll"):
                yield Static(self._lines, id="confirm-lines")
            with Horizontal(classes="buttons"):
                yield ActionButton(
                    "y", self._yes, press_key="y", id="confirm-yes", classes="-strong"
                )
                yield ActionButton("n", self._no, press_key="n", id="confirm-no", classes="-plain")

    def on_mount(self) -> None:
        self.query_one("#confirm-dialog").border_title = f" {self._title} "
        self._fit()

    def on_resize(self) -> None:
        self._fit()

    def _fit(self) -> None:
        """Keep clear of the poster panel, and give the lines no more rows than leave
        the buttons on screen."""
        keep_clear_of_posters(self.query_one("#confirm-dialog"))
        rows = max(1, self.app.size.height - _CHROME_ROWS)
        self.query_one("#confirm-scroll").styles.max_height = rows

    def action_scroll_lines(self, how: str) -> None:
        """Scroll the lines: ``up``, ``down``, ``page_up``, ``page_down``, ``home`` or ``end``."""
        scroll = self.query_one("#confirm-scroll", VerticalScroll)
        getattr(scroll, f"scroll_{how}")(animate=False)

    def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
