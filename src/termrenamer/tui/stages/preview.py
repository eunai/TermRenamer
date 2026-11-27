"""The Preview Stage: the selected Title's details on the left, the Title list on the right.

The details column holds the selected Title's name, status word and counts, one cell
per video, the summary of the whole Plan and the Apply action. ``↑`` ``↓`` select a
Title, ``←`` ``→`` a file of it; the footer shows that file's current and new paths.
The column stays left of the Title list, where the Poster panel goes (#29).
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import EntryStatus, Plan, PlanEntry
from termrenamer.core.planning import PutBack, derive_plan
from termrenamer.core.title_rows import PlanCounts, TitleRow, title_rows
from termrenamer.tui.stages.title_list_stage import TitleListStage
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.title_details import TitleDetails
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import agree, match_name, plural, why_not_renamed

_LABEL_WIDTH = 6
"""``from`` and ``to`` and the spaces after them, in the footer."""


class _DetailsScroll(VerticalScroll, can_focus=False):
    """The details column's scroll. It never takes focus, so the arrows reach the app's
    key table even when the column is taller than the screen."""


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
        padding: 0 1 0 3;
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
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._plan: Plan | None = None
        self._rows: tuple[TitleRow, ...] = ()
        self._file = 0

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="details"):
                with _DetailsScroll(id="details-scroll"):
                    yield TitleDetails()
                # Under the scroll, so the actions stay on screen however long the Title.
                with Vertical(id="details-actions"):
                    yield ActionButton(
                        "t", "Change match", press_key="t", id="change-match", classes="-plain"
                    )
                    yield ActionButton(
                        "x", "Leave out", press_key="x", id="leave-out", classes="-plain"
                    )
                with Vertical(id="preview-summary"):
                    yield Static("", id="summary-counts")
                    yield ActionButton("enter", "Apply…", press_key="enter", classes="-strong")
                    yield Static("Nothing moves until you confirm.", id="preview-note")
            with Vertical(classes="stage-body"):
                yield from self.compose_heading()
                yield TitleList(id="preview-titles")

    def on_mount(self) -> None:
        # Each button shows once its key's action is built, here or on the app (#28).
        for button_id, action in (("#change-match", "pick_match"), ("#leave-out", "leave_out")):
            built = any(callable(getattr(n, f"action_{action}", None)) for n in (self, self.app))
            self.query_one(button_id).display = built

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

    def show_plan(self, plan: Plan, *, keep_selection: bool = False) -> None:
        """Show ``plan``'s Titles, and each not recognised video as a row of its own.

        A new Plan starts at its first row. With ``keep_selection``, for a Plan
        derived from the one shown, the selection stays on the same file, in whichever
        row now holds it, found by the source the Plan recorded for it.
        """
        kept = self._kept_entry(plan) if keep_selection else None
        self._plan = plan
        self._rows = title_rows(plan)
        self._file = 0
        row_index = 0
        if kept is not None:
            for index, row in enumerate(self._rows):
                if kept in row.files:
                    row_index, self._file = index, row.files.index(kept)
                    break
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
        if rows:
            self.title_list.highlighted = row_index
        self.show_heading_count(len(rows))
        self.query_one("#summary-counts", Static).update(_summary(PlanCounts.of(plan)))
        self._show_details()

    def _kept_entry(self, plan: Plan) -> PlanEntry | None:
        """The entry of ``plan`` with the selected file's recorded source, or ``None``."""
        selected = self.selected_file
        if selected is None:
            return None
        return _entry_of(plan, selected)

    def redraw(self) -> None:
        super().redraw()
        self._show_details()

    def _show_details(self) -> None:
        if self._plan is not None:
            self.query_one(TitleDetails).show(self.selected_row, self._plan.mode, self._file)
        video = self.selected_file
        left_out = video is not None and video.status is EntryStatus.LEFT_OUT
        self.query_one("#leave-out", ActionButton).update(
            "x  Put back" if left_out else "x  Leave out"
        )
        self.changed()

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
        if video.status is EntryStatus.LEFT_OUT and self._plan is not None:
            to = str(_name_if_put_back(self._plan, video))
        if why is None:
            colour = "$warning" if video.status is EntryStatus.NAME_TAKEN else "$accent"
        elif video.status is EntryStatus.READY:
            colour = "$tr-dim"
        elif video.status is EntryStatus.LEFT_OUT:
            colour = "$tr-dim strike"  # the name it would have, struck through
        else:
            colour = StatusWord(video.status).style
        return (
            f"[$tr-dim]from[/]  [$foreground]{escape(fit_path(str(video.source), width))}[/]",
            f"[$tr-dim]to[/]    [{colour}]{escape(fit_path(to, width - len(note)))}[/]"
            f"[$tr-dim]{escape(note)}[/]",
        )


def _name_if_put_back(plan: Plan, video: PlanEntry) -> Path | None:
    """The name the left out ``video`` would get if it were put back now, or its wanted
    name when it would get none (Name taken ``skip``) or the disk cannot be tested."""
    try:
        back = derive_plan(plan, PutBack(video))
    except OSError:
        return video.wanted
    put_back = _entry_of(back, video)
    destination = put_back.destination if put_back is not None else None
    return destination or video.wanted


def _entry_of(plan: Plan, entry: PlanEntry) -> PlanEntry | None:
    """The entry of ``plan`` (derived from the Plan ``entry`` came from) that records the
    same source: the Plan's own record, compared without reading the disk."""
    return next((e for e in plan.entries if e.source == entry.source), None)


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
    """The Plan's videos counted by status, on three lines to fit the column."""

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
            part(counts.left_out, StatusWord.LEFT_OUT),
        )
    )
