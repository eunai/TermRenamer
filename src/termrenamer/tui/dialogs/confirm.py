"""A yes-or-no confirm: a titled box of lines over the Title list, with two buttons.

It returns ``True`` for ``y`` and ``False`` for ``n`` or Escape; a subclass may add
``enter`` for yes. It sits right of where the Poster panel goes.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Static

from termrenamer.tui.widgets.action_button import ActionButton


class ConfirmDialog(ModalScreen[bool]):
    """``title`` over ``lines``, then the yes button (``y``) and the no button (``n``).

    ``lines`` is a :class:`~textual.content.Content`, so a caller decides what is markup:
    a path or a file name in it is never read as markup unless the caller made it so.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
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
    ConfirmDialog #confirm-lines {
        height: auto;
        padding: 1 0 1 0;
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
            yield Static(self._lines, id="confirm-lines")
            with Horizontal(classes="buttons"):
                yield ActionButton(
                    "y", self._yes, press_key="y", id="confirm-yes", classes="-strong"
                )
                yield ActionButton("n", self._no, press_key="n", id="confirm-no", classes="-plain")

    def on_mount(self) -> None:
        self.query_one("#confirm-dialog").border_title = f" {self._title} "

    def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
