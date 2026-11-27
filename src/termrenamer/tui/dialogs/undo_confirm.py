"""The Undo confirm: nothing is put back until the person answers yes.

It returns ``True`` for ``y`` and ``False`` for ``n`` or Escape. It sits where the Apply
confirm sits. Its lines are plain text: no path or name is read as markup.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Static

from termrenamer.core.models import ApplyOutcome
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.words import agree, plural


def undo_lines(outcome: ApplyOutcome) -> tuple[str, ...]:
    """What the confirm says: the videos and Sidecars put back, the Stragglers that go
    back with them, and the folders made again; each line only when it counts any.

    A file is told from a Straggler's by its recorded old path, as text: an entry's is
    the source of one of the outcome's results.
    """
    entries = {str(result.source) for result in outcome.results}
    files = sum(1 for move in outcome.moves if str(move.source) in entries)
    # Each Straggler's moved file is the Straggler itself, or a file inside it.
    moved = {
        str(path)
        for move in outcome.moves
        if str(move.source) not in entries
        for path in (move.source, *move.source.parents)
    }
    stragglers = sum(1 for result in outcome.stragglers if str(result.source) in moved)
    folders = len(outcome.folders_removed)
    lines = []
    if files:
        lines.append(
            f"Put {plural(files, 'file')} back where {agree(files, 'it was', 'they were')}."
        )
    if stragglers:
        lines.append(
            "The Straggler goes back too."
            if stragglers == 1
            else f"The {stragglers} Stragglers go back too."
        )
    if folders:
        lines.append(
            "The removed folder is made again."
            if folders == 1
            else f"The {folders} removed folders are made again."
        )
    return tuple(lines)


class UndoConfirm(ModalScreen[bool]):
    """ "Undo the last Apply?" with what Undo will do (:func:`undo_lines`), and Put back
    or Keep."""

    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
    ]

    DEFAULT_CSS = """
    UndoConfirm {
        align: right middle;
        background: $background 60%;
    }
    UndoConfirm #undo-dialog {
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
    UndoConfirm #undo-lines {
        height: auto;
        padding: 1 0 1 0;
    }
    UndoConfirm .buttons {
        height: 1;
        margin-bottom: 1;
    }
    UndoConfirm .buttons ActionButton {
        margin: 0 2 0 0;
    }
    """

    def __init__(self, outcome: ApplyOutcome) -> None:
        super().__init__()
        self._lines = undo_lines(outcome)

    def compose(self) -> ComposeResult:
        with Vertical(id="undo-dialog"):
            yield Static(Content("\n".join(self._lines)), id="undo-lines")
            with Horizontal(classes="buttons"):
                yield ActionButton("y", "Put back", press_key="y", id="undo-yes", classes="-strong")
                yield ActionButton("n", "Keep", press_key="n", id="undo-no", classes="-plain")

    def on_mount(self) -> None:
        self.query_one("#undo-dialog").border_title = " Undo the last Apply? "

    def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        self.dismiss(event.button.id == "undo-yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
