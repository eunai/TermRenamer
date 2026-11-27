"""The Apply confirm: nothing is renamed until the person answers yes.

It returns ``True`` for ``y`` or ``enter`` and ``False`` for ``n`` or Escape. It sits
over the Title list, right of where the poster panel goes.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Static

from termrenamer.tui.widgets.action_button import ActionButton


class ApplyConfirm(ModalScreen[bool]):
    """ "Apply the Plan?" with how many videos will be renamed, and Apply or Back."""

    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("enter", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
    ]

    DEFAULT_CSS = """
    ApplyConfirm {
        align: right middle;
        background: $background 60%;
    }
    ApplyConfirm #confirm-dialog {
        width: 62;
        max-width: 100%;
        height: 12;
        margin-right: 12;
        padding: 0 2;
        border: round $accent;
        border-title-color: $foreground;
        border-title-style: bold;
        background: $tr-dialog;
    }
    ApplyConfirm #confirm-lines {
        height: 6;
        padding: 1 0 0 0;
    }
    ApplyConfirm .buttons {
        height: 1;
    }
    ApplyConfirm .buttons ActionButton {
        margin: 0 2 0 0;
    }
    """

    def __init__(self, *, videos: int, under: str, no_match: int, not_recognised: int) -> None:
        super().__init__()
        self._videos = videos
        self._under = under
        self._skipped = f"Skip {no_match} with no match · {not_recognised} not recognised"

    def compose(self) -> ComposeResult:
        noun = "video" if self._videos == 1 else "videos"
        with Vertical(id="confirm-dialog"):
            yield Static(
                f"[$foreground]Rename {self._videos} {noun} {escape(self._under)}.[/]\n"
                f"[$foreground]{self._skipped}[/]\n\n"
                "[$warning]Nothing has been renamed yet.[/]",
                id="confirm-lines",
            )
            with Horizontal(classes="buttons"):
                yield ActionButton("y", "Apply", press_key="y", id="confirm-yes", classes="-strong")
                yield ActionButton("n", "Back", press_key="n", id="confirm-no", classes="-plain")

    def on_mount(self) -> None:
        self.query_one("#confirm-dialog").border_title = " Apply the Plan? "

    def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
