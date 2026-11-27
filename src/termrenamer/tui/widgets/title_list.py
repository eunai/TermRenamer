"""The Title list: one row per Title with its name, a coloured status word and a count.

The Plan Stage and the Preview Stage both show it. It never takes focus: the app's
``↑`` ``↓`` keys move its selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class StatusWord(StrEnum):
    """A row's status word: a Plan entry's status, or ``found`` while the Plan is built."""

    READY = "ready"
    FOUND = "found"
    NAME_TAKEN = "name taken"
    NO_MATCH = "no match"
    NOT_RECOGNISED = "not recognised"

    @property
    def colour(self) -> str:
        """The theme variable the word is written in."""
        return _COLOURS[self]


_COLOURS = {
    StatusWord.READY: "success",
    StatusWord.FOUND: "success",
    StatusWord.NAME_TAKEN: "warning",
    StatusWord.NO_MATCH: "error",
    StatusWord.NOT_RECOGNISED: "error",
}


@dataclass(frozen=True, slots=True)
class ListRow:
    """What one row shows. ``key`` identifies the row; ``count`` may be blank."""

    key: str
    name: str
    status: StatusWord
    count: str


class TitleList(OptionList, can_focus=False):
    """The list of :class:`ListRow` s, the selected one highlighted."""

    DEFAULT_CSS = """
    TitleList {
        height: 1fr;
        border: none;
        background: $background;
        padding: 0;
        scrollbar-size-vertical: 1;
    }
    TitleList > .option-list--option-highlighted {
        background: $tr-highlight;
    }
    TitleList:focus {
        border: none;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._rows: list[ListRow] = []

    @property
    def rows(self) -> tuple[ListRow, ...]:
        return tuple(self._rows)

    @property
    def selected(self) -> ListRow | None:
        """The highlighted row, or ``None`` when the list is empty."""
        index = self.highlighted
        if index is None or not (0 <= index < len(self._rows)):
            return None
        return self._rows[index]

    def set_rows(self, rows: list[ListRow]) -> None:
        """Show ``rows``, keeping the selection on the same row when it is still there."""
        previous = self.selected
        self._rows = list(rows)
        self.set_options(self._prompt(row) for row in self._rows)
        keys = [row.key for row in self._rows]
        if previous is not None and previous.key in keys:
            self.highlighted = keys.index(previous.key)
        elif self._rows:
            self.highlighted = 0

    def put_row(self, row: ListRow) -> None:
        """Add ``row``, or replace the row with the same key."""
        keys = [r.key for r in self._rows]
        if row.key in keys:
            index = keys.index(row.key)
            self._rows[index] = row
            self.replace_option_prompt_at_index(index, self._prompt(row).prompt)
            return
        self._rows.append(row)
        self.add_option(self._prompt(row))
        if self.highlighted is None:
            self.highlighted = 0

    def redraw(self) -> None:
        """Draw every row again, as after a change of theme."""
        self.set_rows(self._rows)

    def select_previous(self) -> None:
        """Select the row above; the first row stays selected."""
        if self.highlighted is not None and self.highlighted > 0:
            self.highlighted -= 1

    def select_next(self) -> None:
        """Select the row below; the last row stays selected."""
        if self.highlighted is not None and self.highlighted < self.option_count - 1:
            self.highlighted += 1

    def _prompt(self, row: ListRow) -> Option:
        colours = self.app.theme_variables
        status_colour = colours.get(row.status.colour, "")
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        grid.add_column(width=14, no_wrap=True)
        grid.add_column(width=4, justify="right", no_wrap=True)
        grid.add_row(
            Text(f"  {row.name}", style=colours.get("foreground", "")),
            Text(row.status, style=status_colour),
            Text(row.count, style=colours.get("tr-dim", "")),
        )
        return Option(grid, id=None)
