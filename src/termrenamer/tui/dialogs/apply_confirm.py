"""The Apply confirm: nothing is renamed until the person answers yes.

It returns ``True`` for ``y`` or ``enter`` and ``False`` for ``n`` or Escape. It sits
over the Title list, right of where the Poster panel goes.
"""

from __future__ import annotations

from collections import Counter

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Static

from termrenamer.core.models import EntryStatus, Plan
from termrenamer.core.title_rows import PlanCounts
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.words import agree, folder_text, plural, why_not_renamed


def confirm_lines(plan: Plan) -> tuple[str, ...]:
    """What the confirm says (Textual markup): the videos renamed and where, the videos
    skipped counted by status, those that already have their names, and that nothing
    has been renamed yet."""
    counts = PlanCounts.of(plan)
    root = plan.options.destination_root
    if root is not None:
        where = f"under {folder_text(root)}"
    else:
        where = agree(counts.to_rename, "in its own folder", "in their own folders")
    staying = [v for v in plan.videos if why_not_renamed(v) is not None]
    named = [v for v in staying if v.has_its_name]
    skipped = Counter(v.status for v in staying if not v.has_its_name)
    if skipped:
        reasons = " · ".join(f"{skipped[s]} {s.value}" for s in EntryStatus if skipped[s])
        skip = f"Skip {plural(skipped.total(), 'video')}: {reasons}"
    else:
        skip = "Skip none."
    lines = [
        f"[$foreground]Rename {plural(counts.to_rename, 'video')} {escape(where)}.[/]",
        f"[$foreground]{skip}[/]",
    ]
    if named:
        that = agree(len(named), "that already has its name", "that already have their names")
        lines.append(f"[$tr-dim]Leave {plural(len(named), 'video')} {that}.[/]")
    lines += ["", "[$warning]Nothing has been renamed yet.[/]"]
    return tuple(lines)


class ApplyConfirm(ModalScreen[bool]):
    """ "Apply the Plan?" with what Apply will do (:func:`confirm_lines`), and Apply or Back."""

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
        height: auto;
        margin-right: 12;
        padding: 0 2;
        border: round $accent;
        border-title-color: $foreground;
        border-title-style: bold;
        background: $tr-dialog;
    }
    ApplyConfirm #confirm-lines {
        height: auto;
        padding: 1 0 1 0;
    }
    ApplyConfirm .buttons {
        height: 1;
    }
    ApplyConfirm .buttons ActionButton {
        margin: 0 2 0 0;
    }
    """

    def __init__(self, plan: Plan) -> None:
        super().__init__()
        self._lines = confirm_lines(plan)

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static("\n".join(self._lines), id="confirm-lines")
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
