"""The Plan Stage: the Title list filling in as the build looks each Title up."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.progress import PlanEvent, TitleLookedUp
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.title_list import ListRow, TitleList


def _display(name: str, year: int | None) -> str:
    return f"{name} ({year})" if year is not None else name


class PlanStage(StageView):
    """Each Title as its lookup finishes, found or not, under "Titles"."""

    DEFAULT_CSS = """
    PlanStage #plan-body {
        height: 1fr;
        padding: 1 2 0 2;
    }
    PlanStage .list-heading {
        height: 2;
        border-bottom: solid $tr-line;
    }
    PlanStage .list-heading Static {
        width: 1fr;
        text-style: bold;
        padding: 0 2;
    }
    PlanStage .list-heading .list-count {
        width: auto;
        color: $tr-dim;
        text-style: none;
    }
    PlanStage #plan-status {
        height: 3;
        padding: 1 2 0 2;
        border-top: solid $tr-line;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="plan-body"):
            with Horizontal(classes="list-heading"):
                yield Static("Titles")
                yield Static("", id="plan-count", classes="list-count")
            yield TitleList(id="plan-titles")
            yield Static("", id="plan-status")

    def start(self, provider: str) -> None:
        """Begin a build on ``provider`` (its name) with an empty list."""
        self.query_one(TitleList).set_rows([])
        self.query_one("#plan-status", Static).update(
            f"[$foreground]Building the Plan[/] [$tr-dim]on {escape(provider)}…[/]"
        )
        self._show_count()

    def report(self, event: PlanEvent) -> None:
        """Draw what the build reported; an event this view does not show is ignored."""
        if isinstance(event, TitleLookedUp):
            self._title_looked_up(event)

    def _title_looked_up(self, event: TitleLookedUp) -> None:
        # Two hints found with the same Match are one Title: one row.
        if event.match is not None:
            row = ListRow(
                key=f"match:{event.match.id}",
                name=_display(event.match.name, event.match.year),
                status="found",
                count="",
            )
        else:
            row = ListRow(
                key=f"hint:{event.name.casefold()}|{event.year}",
                name=_display(event.name, event.year),
                status="no match",
                count="",
            )
        self.query_one(TitleList).put_row(row)
        self._show_count()
        self.changed()

    def _show_count(self) -> None:
        self.query_one("#plan-count", Static).update(str(len(self.query_one(TitleList).rows)))

    def count_text(self) -> str:
        n = len(self.query_one(TitleList).rows)
        return f"{n} Title{'' if n == 1 else 's'} looked up"

    def redraw(self) -> None:
        self.query_one(TitleList).redraw()

    def action_select_previous(self) -> None:
        self.query_one(TitleList).select_previous()
        self.changed()

    def action_select_next(self) -> None:
        self.query_one(TitleList).select_next()
        self.changed()
