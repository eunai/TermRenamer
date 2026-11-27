"""The selected Title's details: its name, status word and counts, and one cell per video.

In TV Mode the cells are grouped by season, each group after its ``S01`` label. A cell
takes its file's status colour, and a mark under it shows the selected file.
"""

from __future__ import annotations

from collections import Counter

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.widgets import Static

from termrenamer.core.models import ScanMode
from termrenamer.core.title_rows import TitleRow
from termrenamer.tui.widgets.title_list import StatusWord
from termrenamer.tui.words import match_name, plural

CELLS_WIDTH = 34
"""The columns the cells may take before they wrap: the inner width of the Preview's
details column (its CSS width 39, less its border and padding, in `stages/preview.py`)."""

_CELL = "██"
_MARK = "▔▔"
_GROUP_GAP = 2


class TitleDetails(Vertical):
    """The heading (name; status word and counts), the tally of a mixed Title, the cells."""

    DEFAULT_CSS = """
    TitleDetails {
        height: auto;
    }
    TitleDetails #details-heading {
        margin-bottom: 1;
    }
    TitleDetails #details-tally {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="details-heading")
        yield Static("", id="details-tally")
        yield Static("", id="details-cells")

    def show(self, row: TitleRow | None, mode: ScanMode, selected: int) -> None:
        """Show ``row`` with its file number ``selected`` marked, or nothing for ``None``."""
        heading = self.query_one("#details-heading", Static)
        tally = self.query_one("#details-tally", Static)
        cells = self.query_one("#details-cells", Static)
        if row is None:
            for part in (heading, tally, cells):
                part.update("")
            return
        name = row.name if row.title is None else match_name(row.title, mode)
        heading.update(
            Content.from_markup(
                f"[b $foreground]$name[/]\n[b {StatusWord(row.status).style}]{row.status.value}[/] "
                "[$tr-dim]· $counts[/]",
                name=name,
                counts=_counts(row, mode),
            )
        )
        statuses = Counter(StatusWord(entry.status) for entry in row.files)
        tally.update(
            " [$tr-dim]·[/] ".join(f"[{s.style}]{n} {s.value}[/]" for s, n in statuses.items())
            if len(statuses) > 1
            else ""
        )
        tally.display = len(statuses) > 1
        cells.update(_cells(row, mode, selected))


def _counts(row: TitleRow, mode: ScanMode) -> str:
    """``1 season · 2 videos`` for a TV Title, ``1927 · 1 video`` for a film."""
    parts = []
    if row.title is not None and mode is ScanMode.FILM and row.title.year is not None:
        parts.append(str(row.title.year))
    seasons = {entry.season for entry in row.files if entry.season is not None}
    if mode is ScanMode.TV and seasons:
        parts.append(plural(len(seasons), "season"))
    parts.append(plural(row.videos, "video"))
    return " · ".join(parts)


def _cells(row: TitleRow, mode: ScanMode, selected: int) -> str:
    """Three text rows per line of cells: the cells' top, their bottom with the season
    label, and the mark under the selected cell. A line that is full wraps."""
    lines: list[list[str]] = []
    current: list[list[str]] = [[], [], []]
    x = 0

    def put(top: str, bottom: str, mark: str, width: int) -> None:
        nonlocal x
        for part, text in zip(current, (top, bottom, mark), strict=True):
            part.append(text)
        x += width

    def new_line(indent: int) -> None:
        nonlocal current, x
        lines.extend(current)
        current, x = [[], [], []], 0
        put(" " * indent, " " * indent, " " * indent, indent)

    blank = " " * (len(_CELL) + 1)
    season: int | None = None
    for index, entry in enumerate(row.files):
        if mode is ScanMode.TV and (index == 0 or entry.season != season):
            season = entry.season
            label = f"S{season:02d}" if season is not None else "S··"
            width = len(label) + 1
            if index:
                if x + _GROUP_GAP + width + len(_CELL) > CELLS_WIDTH:
                    new_line(0)
                else:
                    gap = " " * _GROUP_GAP
                    put(gap, gap, gap, _GROUP_GAP)
            put(" " * width, f"[$tr-dim]{label}[/] ", " " * width, width)
        elif x + len(_CELL) > CELLS_WIDTH:
            new_line(4 if mode is ScanMode.TV else 0)
        style = StatusWord(entry.status).style
        cell = f"[{style}]{_CELL}[/] "
        put(cell, cell, f"[$accent]{_MARK}[/] " if index == selected else blank, len(blank))
    lines.extend(current)
    return "\n".join("".join(parts).rstrip() for parts in lines)
