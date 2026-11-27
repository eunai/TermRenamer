"""The Preview Stage: the selected Title's details on the left, the Title list on the right.

The details column holds the selected Title's name, status word and counts, one cell
per video, the summary of the whole Plan and the Apply action. ``↑`` ``↓`` select a
Title, ``←`` ``→`` a file of it; the footer shows that file's current and new paths.

While Posters are shown, the poster panel tops the column, outside the details' scroll,
and the selected Title's Poster is downloaded when it is not stored yet. The summary
and Apply then move under the Title list, as the mockup draws them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from termrenamer.core.models import EntryStatus, Plan, PlanEntry
from termrenamer.core.planning import PutBack, derive_plan
from termrenamer.core.title_rows import PlanCounts, TitleRow, title_rows
from termrenamer.tui.stages.title_list_stage import TitleListStage
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.footer import FOOTER_FIXED_ROWS
from termrenamer.tui.widgets.header import HEADER_ROWS
from termrenamer.tui.widgets.poster_panel import PANEL_HEIGHT, PosterPanel
from termrenamer.tui.widgets.stages_row import STAGES_ROW_ROWS
from termrenamer.tui.widgets.title_details import COMPACT_ROWS, TitleDetails
from termrenamer.tui.widgets.title_list import ListRow, StatusWord, TitleList
from termrenamer.tui.words import agree, match_name, plural, why_not_renamed

_LABEL_WIDTH = 6
"""``from`` and ``to`` and the spaces after them, in the footer."""

_DETAILS_PADDING_TOP = 1
"""The row above the details in their scroll."""

_ACTION_ROWS = 2
"""Change match and Leave out, on rows of their own one under the other while the
poster panel shows, as the mockup draws them."""

_FOOTER_LINES = 2
"""The Preview's lines in the footer: the selected file's ``from`` and ``to``."""

ROWS_FOR_POSTERS = (
    HEADER_ROWS
    + STAGES_ROW_ROWS
    + PANEL_HEIGHT
    + _DETAILS_PADDING_TOP
    + COMPACT_ROWS
    + _ACTION_ROWS
    + FOOTER_FIXED_ROWS
    + _FOOTER_LINES
)
"""The fewest rows that hold the Preview with the poster panel: the panel, the compact
details and both actions in the column, the header and footer above and below. Below
this the panel is hidden, as if Posters were off."""


def _apply_parts(button_id: str, note_id: str) -> ComposeResult:
    """The Apply button and its note, for the summary beside the details or under the list."""
    yield ActionButton("enter", "Apply…", press_key="enter", id=button_id, classes="-strong")
    yield Static("Nothing moves until you confirm.", id=note_id)


class _DetailsScroll(VerticalScroll, can_focus=False):
    """The details column's scroll. It never takes focus, so the arrows reach the app's
    key table even when the column is taller than the screen."""


_WAITING_ACTIONS = ("apply", "leave_out", "pick_match")
"""The actions that wait while a picked Match's episodes are looked up."""
_WAITING_BUTTONS = ("#apply", "#apply-under", "#leave-out", "#change-match")
"""Their buttons, off the screen meanwhile."""


class PreviewStage(TitleListStage):
    """The details column with the summary and Apply, and the Plan's Title list."""

    DEFAULT_CSS = (
        """
    PreviewStage #details {
        width: 39;
        height: 1fr;
        border-right: solid $tr-line;
    }
    PreviewStage #details-scroll {
        width: 100%;  /* 1fr would lose the poster panel's left margin */
        height: 1fr;
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
    PreviewStage.-posters #details-actions ActionButton {
        margin: 0;
    }
    """
        + f"""
    PreviewStage #details-scroll {{
        padding: {_DETAILS_PADDING_TOP} 1 0 3;
    }}
    """
    )

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._plan: Plan | None = None
        self._rows: tuple[TitleRow, ...] = ()
        self._file = 0
        self._shown_row: int | None = None
        """The row the details, the footer and the Poster show; a click that highlights
        another row selects that row's first file."""
        self._looking_up = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="details"):
                yield PosterPanel(id="preview-poster")
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
                    yield Static("", id="summary-counts", classes="summary-counts")
                    yield from _apply_parts("apply", "preview-note")
            with Vertical(classes="stage-body"):
                yield from self.compose_heading()
                yield TitleList(id="preview-titles")
                # The same summary and Apply, under the list while the poster panel shows.
                with Vertical(id="summary-under"):
                    yield Static("", id="summary-counts-under", classes="summary-counts")
                    with Horizontal(id="summary-under-apply"):
                        yield from _apply_parts("apply-under", "summary-under-note")

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
        self._show_looking_up(False)
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
        summary = _summary(PlanCounts.of(plan))
        for counts in self.query(".summary-counts").results(Static):
            counts.update(summary)
        self._show_details()

    def mark_looking_up(self) -> None:
        """Mark the selected Title looking up, while its new Match's episodes are looked
        up; showing a Plan clears the mark. Apply, Leave out and Change match wait: their
        keys leave the footer and their buttons the screen."""
        selected = self.title_list.selected
        if selected is not None:
            self.title_list.put_row(replace(selected, status=StatusWord.LOOKING_UP))
        self._show_looking_up(True)
        self.changed()

    def _show_looking_up(self, looking_up: bool) -> None:
        self._looking_up = looking_up
        for button_id in _WAITING_BUTTONS:
            self.query_one(button_id).visible = not looking_up

    def key_enabled(self, action: str) -> bool:
        return not (self._looking_up and action in _WAITING_ACTIONS)

    def _kept_entry(self, plan: Plan) -> PlanEntry | None:
        """The entry of ``plan`` with the selected file's recorded source, or ``None``."""
        selected = self.selected_file
        if selected is None:
            return None
        return _entry_of(plan, selected)

    def redraw(self) -> None:
        super().redraw()
        self._show_details()

    def row_highlighted(self) -> None:
        if self.title_list.highlighted != self._shown_row:
            self._file = 0
            self._show_details()

    def _show_details(self) -> None:
        self._shown_row = self.title_list.highlighted
        if self._plan is not None:
            self.query_one(TitleDetails).show(
                self.selected_row, self._plan.mode, self._file, compact=self.posters_shown
            )
            self._show_poster()
            # Once the details are laid out, the selected file's mark is scrolled to.
            self.call_after_refresh(self._keep_mark_in_view)
        video = self.selected_file
        left_out = video is not None and video.status is EntryStatus.LEFT_OUT
        self.query_one("#leave-out", ActionButton).update(
            "x  Put back" if left_out else "x  Leave out"
        )
        # Change match stands out on a row with no match, as in the mockup.
        row = self.selected_row
        unmatched = row is not None and row.status in (
            EntryStatus.NO_MATCH,
            EntryStatus.NOT_RECOGNISED,
        )
        change = self.query_one("#change-match", ActionButton)
        change.set_class(unmatched, "-strong")
        change.set_class(not unmatched, "-plain")
        self.changed()

    def _keep_mark_in_view(self) -> None:
        """Scroll the details the least that brings the selected file's mark on screen."""
        region = self.query_one(TitleDetails).mark_region()
        if region is None:
            return
        scroll = self.query_one("#details-scroll", VerticalScroll)
        content = scroll.scrollable_content_region
        scroll.scroll_to_region(
            region.translate((-content.x, int(scroll.scroll_y) - content.y)),
            animate=False,
            immediate=True,
        )

    def _show_poster(self) -> None:
        """The selected Title's Poster, downloaded now when it is not stored yet."""
        plan, row = self._plan, self.selected_row
        panel = self.query_one(PosterPanel)
        if plan is None or row is None:
            panel.clear()
            return
        name = row.name if row.title is None else match_name(row.title, plan.mode)
        ref = row.title.poster_ref if row.title is not None else None
        panel.show(name, provider_id=plan.options.provider_id, ref=ref, download=True)

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

    def footer_lines(self) -> tuple[Content, ...]:
        row, video = self.selected_row, self.selected_file
        if row is None or video is None:
            return ()
        width = footer_path_width(self.app.size.width)
        why = why_not_renamed(video)
        notes = [why] if why is not None else []
        if why is None and video.status is EntryStatus.NAME_TAKEN:
            notes.append("name taken, gets a number")
        notes.extend(_sidecar_notes(row.sidecars_of(video), moves=why is None))
        note = "".join(f" · {n}" for n in notes)
        to = str(video.destination) if video.destination is not None else "not renamed"
        named_if_put_back = False
        if video.status is EntryStatus.LEFT_OUT and self._plan is not None:
            back = _name_if_put_back(self._plan, video)
            # A file with no new name (not recognised, no match) stays where it is.
            if back is not None:
                to, named_if_put_back = str(back), True
        if why is None:
            colour = "$warning" if video.status is EntryStatus.NAME_TAKEN else "$accent"
        elif video.status is EntryStatus.READY:
            colour = "$tr-dim"
        elif video.status is EntryStatus.LEFT_OUT:
            # The name it would have, struck through; "not renamed" when it has none.
            colour = "$tr-dim strike" if named_if_put_back else "$tr-dim"
        else:
            colour = StatusWord(video.status).style
        return (
            Content.from_markup(
                "[$tr-dim]from[/]  [$foreground]$source[/]",
                source=fit_path(str(video.source), width),
            ),
            Content.from_markup(
                f"[$tr-dim]to[/]    [{colour}]$to[/][$tr-dim]$note[/]",
                to=fit_path(to, width - len(note)),
                note=note,
            ),
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


def footer_path_width(screen_width: int) -> int:
    """The cells the footer gives a path on a screen ``screen_width`` cells wide."""
    return max(20, screen_width - 4 - _LABEL_WIDTH)


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
    """The Plan's videos counted by status, on three lines to fit the column, and the
    Stragglers to merge when there are any."""

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
            part(counts.left_out, StatusWord.LEFT_OUT) + _stragglers_part(counts.stragglers),
        )
    )


def _stragglers_part(n: int) -> str:
    """`` · 2 Stragglers merge`` (Textual markup), or nothing for none."""
    if not n:
        return ""
    return f" [$tr-dim]· {plural(n, 'Straggler')} {agree(n, 'merges', 'merge')}[/]"
