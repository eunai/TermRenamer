"""The Plan Stage: how far the build is, each Title's lookup, and Escape to cancel.

The view draws what the build's listener reports (:mod:`termrenamer.core.progress`):
the Title list with each Title waiting, looking up, found or not found; "N of M files
looked up"; and a strip with the lookup gauge, the matched and unmatched bars and
lookups per second. The selected Title's details sit in the left column, under the
poster panel while Posters are shown. No Poster is downloaded while the Plan is built:
the panel draws a Poster the store already holds, and otherwise the Title's name and
status word.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static

from termrenamer.core.models import Candidate, ScanMode
from termrenamer.core.progress import (
    BuildFinished,
    FileLookedUp,
    PlanEvent,
    Scanned,
    TitleLookedUp,
    TitleLookupStarted,
)
from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.lookup_rate import LookupRate
from termrenamer.tui.stages.title_list_stage import TitleListStage
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.poster_panel import NO_POSTER, PosterPanel
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import match_name, plural, provider_name, title_name

_DETAILS_WIDTH = 39
"""The left column's width with its rule, as in the mockup and the Preview Stage."""

_WIDE_STRIP = 116
"""The strip's width at the design size (120 columns less its padding)."""
_WIDE_CELLS = (16, 16, 8, 10, 3)
_NARROW_CELLS = (6, 6, 3, 5, 2)
"""The strip's cells: the lookup gauge, the matched bar, the unmatched bar, the
lookups per second chart and the gap between the four, at the design size and below."""


@dataclass(slots=True)
class _Row:
    """One row of the list while the Plan is built: a Title, or a not recognised video."""

    key: str
    name: str
    videos: int
    status: StatusWord
    match: Candidate | None = None
    year: int | None = None
    looked_up: int = 0

    def list_row(self) -> ListRow:
        return ListRow(self.key, self.name, self.status, str(self.videos))


def _hint_key(name: str, year: int | None) -> str:
    return f"hint:{name.casefold().strip()}|{year}"


class PlanStage(TitleListStage):
    """The build's progress: the Title list, the files looked up, and the lookup strip."""

    DEFAULT_CSS = f"""
    PlanStage #plan-columns {{
        height: 1fr;
    }}
    PlanStage #plan-left {{
        width: {_DETAILS_WIDTH};
        height: 100%;
        border-right: solid $tr-line;
    }}
    PlanStage #plan-details {{
        height: auto;
        padding: 1 3;
    }}
    PlanStage #plan-status {{
        height: auto;
        padding: 1 0 1 1;
        border-top: solid $tr-line;
    }}
    PlanStage #plan-provider {{
        color: $tr-dim;
        margin: 0 0 1 0;
    }}
    PlanStage #plan-strip {{
        height: 2;
        padding: 0 2;
        border-top: solid $tr-line;
    }}
    """

    class CancelRequested(Message):
        """The person asked to cancel the build (Escape at the Plan Stage)."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.clock: Callable[[], float] = time.monotonic
        """The rate's clock; a test sets its own before the build."""
        self._mode = ScanMode.TV
        self._provider_id = ""
        self._provider = ""
        self._rows: list[_Row] = []
        self._row_of: dict[str, _Row] = {}
        self._current: _Row | None = None
        self._total = 0
        self._looked_up = 0
        self._matched = 0
        self._unmatched = 0
        self._rate = LookupRate(self.clock)
        self._timer: Timer | None = None
        self._building = False
        """Whether a build runs; once it ends the panel holds no Poster."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="plan-columns"):
            # The selected Title's details: its name, status word and videos.
            with Vertical(id="plan-left"):
                yield PosterPanel(id="plan-poster")
                yield Static("", id="plan-details")
            with Vertical(classes="stage-body"):
                yield from self.compose_heading()
                yield TitleList(id="plan-titles")
                with Vertical(id="plan-status"):
                    yield Static("", id="plan-progress")
                    yield Static("", id="plan-provider")
                    yield ActionButton(
                        "esc", "Cancel the Plan", press_key="escape", classes="-plain"
                    )
        yield Static("", id="plan-strip")

    # ----------------------------------------------------------- the build

    def start(self, provider_id: str, mode: ScanMode) -> None:
        """Begin a build in ``mode`` on the Provider ``provider_id``, with an empty list."""
        self._mode = mode
        self._provider_id = provider_id
        self._provider = provider_name(provider_id)
        self._building = True
        self._rows = []
        self._row_of = {}
        self._current = None
        self._total = self._looked_up = self._matched = self._unmatched = 0
        # The rate counts from the key press, not from when the screen hears the scan.
        self._rate = LookupRate(self.clock)
        self.title_list.set_rows([])
        self._draw_rows()
        self._draw_progress()

    def stop(self) -> None:
        """The build ended or was cancelled: the rate stops moving, the panel empties."""
        self._stop_timer()
        self._building = False
        self.query_one(PosterPanel).view.clear()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def report(self, event: PlanEvent) -> None:
        """Draw what the build reported; an event this view does not show is ignored."""
        if isinstance(event, Scanned):
            self._scanned(event)
        elif isinstance(event, TitleLookupStarted):
            self._set_status(_hint_key(event.name, event.year), StatusWord.LOOKING_UP)
        elif isinstance(event, TitleLookedUp):
            self._title_looked_up(event)
        elif isinstance(event, FileLookedUp):
            self._file_looked_up(event)
        elif isinstance(event, BuildFinished):
            self.stop()
            self._draw_progress()

    def _scanned(self, event: Scanned) -> None:
        self._total = event.files
        self._rows = [
            _Row(
                key=_hint_key(t.name, t.year),
                name=title_name(t.name, t.year, self._mode),
                videos=t.videos,
                status=StatusWord.WAITING,
                year=t.year,
            )
            for t in event.titles
        ]
        self._rows += [
            _Row(key=f"file:{path}", name=path.name, videos=1, status=StatusWord.NOT_RECOGNISED)
            for path in event.not_recognised
        ]
        self._row_of = {row.key: row for row in self._rows}
        self.title_list.set_rows([row.list_row() for row in self._rows])
        self._stop_timer()
        self._timer = self.set_interval(1.0, self._draw_progress)
        self._draw_rows()
        self._draw_progress()

    def _set_status(self, key: str, status: StatusWord) -> None:
        row = self._row_of.get(key)
        if row is None:
            return
        row.status = status
        self._current = row
        self.title_list.put_row(row.list_row())
        self._draw_rows()

    def _title_looked_up(self, event: TitleLookedUp) -> None:
        key = _hint_key(event.name, event.year)
        row = self._row_of.get(key)
        if row is None:
            return
        if event.match is None:
            self._set_status(key, StatusWord.NO_MATCH)
            return
        # Two hints found with the same Match are one Title: the later row joins the earlier.
        same = next(
            (r for r in self._rows if r.match is not None and r.match.id == event.match.id), None
        )
        if same is not None:
            selected = self.title_list.selected
            same.videos += row.videos
            self._rows.remove(row)
            self._row_of[key] = same
            self._current = same
            self.title_list.set_rows([r.list_row() for r in self._rows])
            if selected is not None and selected.key == row.key:
                self.title_list.highlighted = self._rows.index(same)
            self._draw_rows()
            return
        row.match = event.match
        row.name = match_name(event.match, self._mode)
        row.year = event.match.year
        self._set_status(key, StatusWord.FOUND)

    def _file_looked_up(self, event: FileLookedUp) -> None:
        self._looked_up += 1
        if event.matched:
            self._matched += 1
        else:
            self._unmatched += 1
        if self._current is not None:
            self._current.looked_up += 1
        self._rate.add()
        self._draw_progress()
        self._draw_details()

    # ------------------------------------------------------------- drawing

    def _draw_rows(self) -> None:
        self.show_heading_count(len(self.title_list.rows))
        self._draw_details()
        self.changed()

    def _draw_progress(self) -> None:
        self.query_one("#plan-progress", Static).update(
            f"{self._looked_up} of {plural(self._total, 'file')} looked up"
        )
        self.query_one("#plan-provider", Static).update(f"on {escape(self._provider)}…")
        self._draw_strip()
        self.changed()

    def _draw_details(self) -> None:
        selected = self.title_list.selected
        row = self._row_of.get(selected.key) if selected is not None else None
        details = self.query_one("#plan-details", Static)
        self._draw_poster(row)
        if row is None:
            details.update("")
            return
        if row.status is StatusWord.LOOKING_UP:
            info = f"{row.looked_up} of {plural(row.videos, 'video')} looked up"
        elif row.status is StatusWord.FOUND and self._mode is ScanMode.FILM and row.year:
            info = f"{row.year} · {plural(row.videos, 'video')}"
        else:
            info = plural(row.videos, "video")
        details.update(
            f"[b]{escape(row.name)}[/]\n"
            f"[${row.status.colour}]{row.status}[/] [$tr-dim]· {escape(info)}[/]"
        )

    def _draw_poster(self, row: _Row | None) -> None:
        """The selected Title's Poster when the store holds it; nothing is downloaded."""
        panel = self.query_one(PosterPanel)
        if row is None or not self._building:
            panel.view.clear()
            return
        ref = row.match.poster_ref if row.match is not None else None
        request = PosterRequest(self._provider_id, ref) if ref else None
        if row.status is StatusWord.LOOKING_UP:
            label = f"{row.status}…"
        elif row.status is StatusWord.WAITING or request is not None:
            label = str(row.status)
        else:
            label = NO_POSTER
        panel.show(row.name, request, provider=self._provider, label=label, download=False)

    def posters_changed(self) -> None:
        self._draw_details()

    def _draw_strip(self) -> None:
        strip = self.query_one("#plan-strip", Static)
        wide = strip.size.width == 0 or strip.size.width >= _WIDE_STRIP
        gauge, bar, small_bar, chart, gap = _WIDE_CELLS if wide else _NARROW_CELLS
        total = self._total
        done = round(self._looked_up / total * gauge) if total else 0
        space = " " * gap
        strip.update(
            f"[$tr-dim]lookups[/] [$accent]{'━' * done}[/][$tr-track]{'━' * (gauge - done)}[/]"
            f" {self._looked_up}/{total}{space}"
            f"[$tr-dim]matched[/] [$success]{_bar(self._matched, total, bar)}[/]"
            f" {self._matched}{space}"
            f"[$tr-dim]unmatched[/] [$error]{_bar(self._unmatched, total, small_bar)}[/]"
            f" {self._unmatched}{space}"
            f"[$tr-dim]lookups/s[/] [$accent]{self._rate.chart(chart)}[/] {self._rate.text()}"
        )

    def on_resize(self) -> None:
        self._draw_strip()

    def redraw(self) -> None:
        super().redraw()
        self._draw_details()
        self._draw_strip()

    # ------------------------------------------------------------ the keys

    def action_select_previous(self) -> None:
        super().action_select_previous()
        self._draw_details()

    def action_select_next(self) -> None:
        super().action_select_next()
        self._draw_details()

    def action_cancel_build(self) -> None:
        """Escape: cancel the build; the app keeps the queue and shows the Queue Stage."""
        self.post_message(self.CancelRequested())

    def count_text(self) -> str:
        return f"{self._looked_up} of {plural(self._total, 'file')}"


def _bar(n: int, total: int, width: int) -> str:
    """A block bar for ``n`` of ``total`` in ``width`` cells; any ``n`` shows one block."""
    if not n or not total:
        return " " * width
    return ("█" * max(1, round(n / total * width))).ljust(width)
