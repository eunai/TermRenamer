"""The Preview Stage: one row per Title with its status word and its count of videos."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import Plan, PlanEntry, videos_of
from termrenamer.core.title_rows import PlanCounts, TitleRow, title_rows
from termrenamer.tui.stages.title_list_stage import TitleListStage, match_name
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import name_taken_note, plural


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
        selected = self.title_list.selected
        if selected is None:
            return None
        return self._rows[int(selected.key)]

    @property
    def selected_file(self) -> PlanEntry | None:
        """The selected Title's first video, by season and episode in TV Mode."""
        row = self.selected_row
        if row is None:
            return None
        files = sorted(videos_of(row.entries), key=lambda e: (e.season or 0, e.episode or 0))
        return files[0] if files else None

    def footer_lines(self) -> tuple[str, ...]:
        """What Apply does with the selected file when its name is taken."""
        selected = self.selected_file
        note = name_taken_note(selected) if selected is not None else None
        if note is None:
            return ()
        return (f"[$warning]{escape(note)}[/]",)

    def show_plan(self, plan: Plan) -> None:
        """Show ``plan``'s Titles, and each not recognised video as a row of its own."""
        self._plan = plan
        self._rows = title_rows(plan)
        rows = [
            ListRow(
                key=str(index),
                name=row.name if row.title is None else match_name(row.title, plan.mode),
                status=StatusWord(row.status.value),
                count=str(row.videos),
            )
            for index, row in enumerate(self._rows)
        ]
        # Rows are keyed by their place, so clear first: a new Plan starts at its first row.
        self.title_list.set_rows([])
        self.title_list.set_rows(rows)
        self.show_heading_count(len(rows))
        self.changed()

    def count_text(self) -> str:
        if self._plan is None:
            return ""
        counts = PlanCounts.of(self._plan)
        return f"{plural(counts.titles, 'Title')} · {plural(counts.videos, 'video')}"
