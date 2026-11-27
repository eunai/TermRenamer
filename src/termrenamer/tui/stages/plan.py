"""The Plan Stage: the Title list filling in as the build looks each Title up."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import ScanMode
from termrenamer.core.progress import PlanEvent, TitleLookedUp
from termrenamer.tui.stages.title_list_stage import TitleListStage, match_name, title_name
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import plural


class PlanStage(TitleListStage):
    """Each Title as its lookup finishes, found or not, under "Titles"."""

    DEFAULT_CSS = """
    PlanStage #plan-status {
        height: 3;
        padding: 1 2 0 2;
        border-top: solid $tr-line;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._mode = ScanMode.TV

    def compose(self) -> ComposeResult:
        with Vertical(classes="stage-body"):
            yield from self.compose_heading()
            yield TitleList(id="plan-titles")
            yield Static("", id="plan-status")

    def start(self, provider: str, mode: ScanMode) -> None:
        """Begin a build in ``mode`` on ``provider`` (its name), with an empty list."""
        self._mode = mode
        self.title_list.set_rows([])
        self.query_one("#plan-status", Static).update(
            f"[$foreground]Building the Plan[/] [$tr-dim]on {escape(provider)}…[/]"
        )
        self.show_heading_count(0)

    def report(self, event: PlanEvent) -> None:
        """Draw what the build reported; an event this view does not show is ignored."""
        if isinstance(event, TitleLookedUp):
            self._title_looked_up(event)

    def _title_looked_up(self, event: TitleLookedUp) -> None:
        # Two hints found with the same Match are one Title: one row.
        if event.match is not None:
            key = f"match:{event.match.id}"
            row = ListRow(key, match_name(event.match, self._mode), StatusWord.FOUND, "")
        else:
            key = f"hint:{event.name.casefold()}|{event.year}"
            row = ListRow(
                key, title_name(event.name, event.year, self._mode), StatusWord.NO_MATCH, ""
            )
        self.title_list.put_row(row)
        self.show_heading_count(len(self.title_list.rows))
        self.changed()

    def count_text(self) -> str:
        return f"{plural(len(self.title_list.rows), 'Title')} looked up"
