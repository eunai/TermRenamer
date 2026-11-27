"""The Preview Stage: one row per Title with its status word and its count of videos."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from termrenamer.core.models import Plan, ScanMode
from termrenamer.core.title_rows import TitleRow, title_rows
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.title_list import ListRow, TitleList


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class PreviewStage(StageView):
    """The Plan's Title list, and the Apply action under it."""

    DEFAULT_CSS = """
    PreviewStage #preview-body {
        height: 1fr;
        padding: 1 2 0 2;
    }
    PreviewStage .list-heading {
        height: 2;
        border-bottom: solid $tr-line;
    }
    PreviewStage .list-heading Static {
        width: 1fr;
        text-style: bold;
        padding: 0 2;
    }
    PreviewStage .list-heading .list-count {
        width: auto;
        color: $tr-dim;
        text-style: none;
    }
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
        with Vertical(id="preview-body"):
            with Horizontal(classes="list-heading"):
                yield Static("Titles")
                yield Static("", id="preview-count", classes="list-count")
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
        film = plan.mode is ScanMode.FILM
        rows = []
        for index, row in enumerate(self._rows):
            name = row.name
            if film and row.title is not None and row.title.year is not None:
                name = f"{name} ({row.title.year})"
            rows.append(
                ListRow(key=str(index), name=name, status=row.status.value, count=str(row.videos))
            )
        title_list = self.query_one(TitleList)
        title_list.set_rows([])
        title_list.set_rows(rows)
        titles = sum(1 for row in self._rows if row.title is not None)
        self.query_one("#preview-count", Static).update(str(titles))
        self.changed()

    def count_text(self) -> str:
        if self._plan is None:
            return ""
        titles = sum(1 for row in self._rows if row.title is not None)
        videos = sum(1 for entry in self._plan.entries if not entry.is_sidecar)
        return f"{_plural(titles, 'Title')} · {_plural(videos, 'video')}"

    def redraw(self) -> None:
        self.query_one(TitleList).redraw()

    def action_select_previous(self) -> None:
        self.query_one(TitleList).select_previous()
        self.changed()

    def action_select_next(self) -> None:
        self.query_one(TitleList).select_next()
        self.changed()
