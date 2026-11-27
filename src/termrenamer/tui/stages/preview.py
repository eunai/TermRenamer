"""The Preview Stage: the selected Title's details on the left, the Title list on the right.

The details column holds the selected Title's name, status word and counts, one cell
per video, the summary of the whole Plan and the Apply action. ``↑`` ``↓`` select a
Title, ``←`` ``→`` a file of it; the footer shows that file's current and new paths.

While Posters are shown, the poster panel tops the column, outside the details' scroll,
and the selected Title's Poster is downloaded when it is not stored yet. The summary
and Apply then move under the Title list, as the mockup draws them.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import EntryStatus, Plan, PlanEntry
from termrenamer.core.title_rows import PlanCounts, TitleRow, title_rows
from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.stages.title_list_stage import TitleListStage
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.poster_panel import PosterPanel
from termrenamer.tui.widgets.title_details import TitleDetails
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import agree, match_name, plural, provider_name, why_not_renamed

_LABEL_WIDTH = 6
"""``from`` and ``to`` and the spaces after them, in the footer."""


class PreviewStage(TitleListStage):
    """The details column with the summary and Apply, and the Plan's Title list."""

    DEFAULT_CSS = """
    PreviewStage #details {
        width: 39;
        height: 1fr;
        border-right: solid $tr-line;
    }
    PreviewStage #details-scroll {
        height: 1fr;
        padding: 1 1 0 3;
        scrollbar-size-vertical: 1;
    }
    PreviewStage #details-actions {
        height: auto;
        margin-top: 1;
    }
    PreviewStage #details-actions ActionButton {
        margin: 0 0 1 0;
    }
    PreviewStage #preview-summary {
        height: auto;
        padding: 1 1 1 3;
        border-top: solid $tr-line;
    }
    PreviewStage #summary-counts {
        margin-bottom: 1;
    }
    PreviewStage #preview-note {
        color: $tr-dim;
        margin-top: 1;
    }
    PreviewStage #summary-under {
        display: none;
        height: auto;
        padding: 1 0 1 3;
        border-top: solid $tr-line;
    }
    PreviewStage #summary-under .summary-counts {
        margin-bottom: 1;
    }
    PreviewStage #summary-under-apply {
        height: 1;
    }
    PreviewStage #summary-under-note {
        width: auto;
        color: $tr-dim;
        margin-left: 2;
    }
    PreviewStage.-posters #preview-summary {
        display: none;
    }
    PreviewStage.-posters #summary-under {
        display: block;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._plan: Plan | None = None
        self._rows: tuple[TitleRow, ...] = ()
        self._file = 0

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="details"):
                yield PosterPanel(id="preview-poster")
                with VerticalScroll(id="details-scroll"):
                    yield TitleDetails()
                    with Vertical(id="details-actions"):
                        yield ActionButton(
                            "t", "Change match", press_key="t", id="change-match", classes="-plain"
                        )
                        yield ActionButton(
                            "x", "Leave out", press_key="x", id="leave-out", classes="-plain"
                        )
                with Vertical(id="preview-summary"):
                    yield Static("", id="summary-counts", classes="summary-counts")
                    yield ActionButton("enter", "Apply…", press_key="enter", classes="-strong")
                    yield Static("Nothing moves until you confirm.", id="preview-note")
            with Vertical(classes="stage-body"):
                yield from self.compose_heading()
                yield TitleList(id="preview-titles")
                # The same summary and Apply, under the list while the poster panel shows.
                with Vertical(id="summary-under"):
                    yield Static("", id="summary-counts-under", classes="summary-counts")
                    with Horizontal(id="summary-under-apply"):
                        yield ActionButton("enter", "Apply…", press_key="enter", classes="-strong")
                        yield Static("Nothing moves until you confirm.", id="summary-under-note")

    def on_mount(self) -> None:
        # Each button shows once its key's action is built (#27, #28).
        for button_id, action in (("#change-match", "pick_match"), ("#leave-out", "leave_out")):
            self.query_one(button_id).display = callable(getattr(self, f"action_{action}", None))

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
        """The selected video of the selected row, or ``None``."""
        row = self.selected_row
        if row is None or not row.files:
            return None
        return row.files[min(self._file, len(row.files) - 1)]

    def show_plan(self, plan: Plan) -> None:
        """Show ``plan``'s Titles, and each not recognised video as a row of its own."""
        self._plan = plan
        self._rows = title_rows(plan)
        self._file = 0
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
        for counts in self.query(".summary-counts").results(Static):
            counts.update(_summary(PlanCounts.of(plan)))
        self._show_details()

    def redraw(self) -> None:
        super().redraw()
        self._show_details()

    def _show_details(self) -> None:
        if self._plan is not None:
            self.query_one(TitleDetails).show(
                self.selected_row, self._plan.mode, self._file, compact=self.posters_shown
            )
            self._show_poster()
        self.changed()

    def _show_poster(self) -> None:
        """The selected Title's Poster, downloaded now when it is not stored yet."""
        plan, row = self._plan, self.selected_row
        panel = self.query_one(PosterPanel)
        if plan is None or row is None:
            panel.view.clear()
            return
        name = row.name if row.title is None else match_name(row.title, plan.mode)
        ref = row.title.poster_ref if row.title is not None else None
        provider_id = plan.options.provider_id
        request = PosterRequest(provider_id, ref) if ref else None
        panel.show(name, request, provider=provider_name(provider_id), download=True)

    def posters_changed(self) -> None:
        self._show_details()

    # ------------------------------------------------------------------ keys

    def action_select_previous(self) -> None:
        self.title_list.select_previous()
        self._file = 0
        self._show_details()

    def action_select_next(self) -> None:
        self.title_list.select_next()
        self._file = 0
        self._show_details()

    def action_previous_file(self) -> None:
        self._file = max(0, self._file - 1)
        self._show_details()

    def action_next_file(self) -> None:
        row = self.selected_row
        if row is not None:
            self._file = max(0, min(self._file + 1, len(row.files) - 1))
        self._show_details()

    # --------------------------------------------------------------- footer

    def count_text(self) -> str:
        if self._plan is None:
            return ""
        counts = PlanCounts.of(self._plan)
        return f"{plural(counts.titles, 'Title')} · {plural(counts.videos, 'video')}"

    def footer_lines(self) -> tuple[str, ...]:
        row, video = self.selected_row, self.selected_file
        if row is None or video is None:
            return ()
        width = max(20, self.app.size.width - 4 - _LABEL_WIDTH)
        why = why_not_renamed(video)
        notes = [why] if why is not None else []
        if why is None and video.status is EntryStatus.NAME_TAKEN:
            notes.append("name taken, gets a number")
        notes.extend(_sidecar_notes(row.sidecars_of(video), moves=why is None))
        note = "".join(f" · {n}" for n in notes)
        to = str(video.destination) if video.destination is not None else "not renamed"
        if why is None:
            colour = "$warning" if video.status is EntryStatus.NAME_TAKEN else "$accent"
        elif video.status is EntryStatus.READY:
            colour = "$tr-dim"
        else:
            colour = StatusWord(video.status).style
        return (
            f"[$tr-dim]from[/]  [$foreground]{escape(fit_path(str(video.source), width))}[/]",
            f"[$tr-dim]to[/]    [{colour}]{escape(fit_path(to, width - len(note)))}[/]"
            f"[$tr-dim]{escape(note)}[/]",
        )


def fit_path(text: str, width: int) -> str:
    """``text`` cut from the left to ``width`` cells, so a path keeps its file name."""
    if len(text) <= width:
        return text
    return "…" + text[-max(1, width - 1) :]


def _sidecar_notes(sidecars: tuple[PlanEntry, ...], *, moves: bool) -> list[str]:
    """How many of a video's Sidecars move with it and how many stay."""
    moving = [s for s in sidecars if moves and why_not_renamed(s) is None]
    staying = len(sidecars) - len(moving)
    notes = []
    if moving:
        n = len(moving)
        notes.append(f"{plural(n, 'Sidecar')} {agree(n, 'moves', 'move')} with it")
    if staying:
        notes.append(f"{plural(staying, 'Sidecar')} {agree(staying, 'stays', 'stay')}")
    return notes


def _summary(counts: PlanCounts) -> str:
    """The Plan's videos counted by status, on three lines to fit the column. Left out
    is dim until it has a status word of its own (#27)."""

    def part(n: int, word: StatusWord) -> str:
        return f"[{word.style}]{n} {word.value}[/]"

    dot = " [$tr-dim]·[/] "
    return "\n".join(
        (
            part(counts.ready, StatusWord.READY)
            + dot
            + part(counts.name_taken, StatusWord.NAME_TAKEN),
            part(counts.no_match, StatusWord.NO_MATCH)
            + dot
            + part(counts.not_recognised, StatusWord.NOT_RECOGNISED),
            f"[$tr-dim]{counts.left_out} left out[/]",
        )
    )
