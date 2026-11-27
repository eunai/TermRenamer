"""What the Plan and Preview Stages share: a "Titles" heading with its count over a Title list."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.title_list import TitleList


class TitleListStage(StageView):
    """A Stage whose body is the Title list; ``↑`` ``↓`` select a row."""

    DEFAULT_CSS = """
    TitleListStage .stage-body {
        height: 1fr;
        padding: 1 2 0 2;
    }
    TitleListStage .list-heading {
        height: 2;
        border-bottom: solid $tr-line;
    }
    TitleListStage .list-heading Static {
        width: 1fr;
        text-style: bold;
        padding: 0 2;
    }
    TitleListStage .list-heading .list-count {
        width: auto;
        color: $tr-dim;
        text-style: none;
    }
    """

    def compose_heading(self) -> ComposeResult:
        with Horizontal(classes="list-heading"):
            yield Static("Titles")
            yield Static("", classes="list-count")

    @property
    def title_list(self) -> TitleList:
        return self.query_one(TitleList)

    def show_heading_count(self, count: int) -> None:
        self.query_one(".list-count", Static).update(str(count))

    def redraw(self) -> None:
        self.title_list.redraw()

    def action_select_previous(self) -> None:
        self.title_list.select_previous()
        self.changed()

    def action_select_next(self) -> None:
        self.title_list.select_next()
        self.changed()
