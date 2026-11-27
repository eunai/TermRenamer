"""The Stages row: Queue, Plan, Preview, Applied; finished ticked, current marked."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import Static

from termrenamer.tui.stage import Stage


def stages_markup(current: Stage) -> str:
    """``✓`` for a finished Stage, ``●`` for the current one, ``○`` for one to come."""
    parts = []
    for stage in Stage:
        if stage.order < current.order:
            parts.append(f"[$success]✓ {stage.value}[/]")
        elif stage is current:
            parts.append(f"[b $accent]● {stage.value}[/]")
        else:
            parts.append(f"[$tr-dim]○ {stage.value}[/]")
    return " [$tr-line]────[/] ".join(parts)


class StagesRow(Horizontal):
    """The four Stages on the left and the current Stage's short count on the right."""

    DEFAULT_CSS = """
    StagesRow {
        height: 2;
        padding: 0 2;
        border-bottom: solid $tr-line;
    }
    StagesRow #stages {
        width: 1fr;
    }
    StagesRow #stage-count {
        width: auto;
        color: $tr-dim;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="stages")
        yield Static(id="stage-count")

    def show(self, current: Stage, count: str) -> None:
        self.query_one("#stages", Static).update(stages_markup(current))
        self.query_one("#stage-count", Static).update(Content(count))
