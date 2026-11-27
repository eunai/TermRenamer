"""The Preview Stage: one row per Title with its status word and its count of videos."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from termrenamer.core.models import Plan
from termrenamer.core.title_rows import PlanCounts, TitleRow, title_rows
from termrenamer.tui.stages.title_list_stage import TitleListStage, match_name
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.title_list import ListRow, TitleList
from termrenamer.tui.words import plural


class PreviewStage(TitleListStage):
    """The Plan's Title list, and the Apply action under it."""

    DEFAULT_CSS = """
    PreviewStage #preview-actions {
        height: 3;
        padding: 1 0 0 0;
        border-top: solid $tr-line;
    }
    PreviewStage #preview-actions ActionButton {
        margin: 0 0 0 2;
    }
    PreviewStage #preview-note {
        width: auto;
        color: $tr-dim;
        padding: 0 2;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._plan: Plan | None = None
        self._rows: tuple[TitleRow, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(classes="stage-body"):
            yield from self.compose_heading()
            yield TitleList(id="preview-titles")
            with Horizontal(id="preview-actions"):
                yield ActionButton("enter", "Apply…", press_key="enter", classes="-strong")
                yield Static("Nothing moves until you confirm.", id="preview-note")

    @property
    def plan(self) -> Plan | None:
        return self._plan

    @property
    def selected_row(self) -> TitleRow | None:
        """The selected row of the Title list, or ``None``."""
        selected = self.query_one(TitleList).selected
        if selected is None:
            return None
        return self._rows[int(selected.key)]

    def show_plan(self, plan: Plan) -> None:
        """Show ``plan``'s Titles, and each not recognised video as a row of its own."""
        self._plan = plan
        self._rows = title_rows(plan)
        rows = [
            ListRow(
                key=str(index),
                name=row.name if row.title is None else match_name(row.title, plan.mode),
                status=row.status.value,
                count=str(row.videos),
            )
            for index, row in enumerate(self._rows)
        ]
        self.title_list.set_rows([])
        self.title_list.set_rows(rows)
        self.show_heading_count(PlanCounts.of(plan).titles)
        self.changed()

    def count_text(self) -> str:
        if self._plan is None:
            return ""
        counts = PlanCounts.of(self._plan)
        return f"{plural(counts.titles, 'Title')} · {plural(counts.videos, 'video')}"
