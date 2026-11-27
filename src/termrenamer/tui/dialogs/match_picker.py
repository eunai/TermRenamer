"""The Match picker: pick a different Match for a Title, or type a title to search again.

It lists the current Match first (marked), then the first Candidate the search found
that is not the current Match, then the "type a title" row, as a plain list. With
no current Match it lists the first two Candidates found. ``↑`` ``↓`` move, ``1`` to ``3`` or
``enter`` choose, ``/`` goes to typing, and Escape closes it with nothing picked.

With Posters shown it draws the same three as picture tiles side by side, as in the
mockup: each Candidate's Poster, or "no poster", with its name, year and key under it,
and the typing field in the third tile. ``←`` ``→`` then move as ``↑`` ``↓`` do. Posters
come from the poster store, drawn at once when stored and otherwise downloaded off
the screen's thread. With Posters hidden or unavailable, or the screen below their
size, it is the plain list; it changes between the two while it is open.

Typing a title and pressing ``enter`` searches the Provider again, off the screen's
thread; the Candidates it finds replace the ones listed, and their Posters. The picker
returns a :class:`Picked` or ``None``; it never changes the Plan itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from termrenamer.core.models import Candidate
from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.poster_support import PosterSource
from termrenamer.tui.widgets.poster_panel import (
    PosterView,
    keep_clear_of_posters,
    room_beside_posters,
)
from termrenamer.util.errors import ProviderError

_LOG = logging.getLogger("termrenamer.tui")

_CANDIDATE_ROWS = 2
"""At most two Candidates are listed at once; typing a more exact title reaches others."""


@dataclass(frozen=True, slots=True)
class TileSize:
    """The tiles' size: the Poster's cells, each tile's columns, and the columns of
    padding on each side of the row of tiles."""

    poster: tuple[int, int]
    tile: int
    padding: int

    @property
    def dialog_width(self) -> int:
        """The dialog's columns with three tiles, one column apart, and its frame."""
        return 3 * self.tile + 2 * _TILE_GAP + 2 * self.padding + 2


_TILE_GAP = 1

TILE_SIZES = (
    TileSize(poster=(20, 15), tile=26, padding=2),
    TileSize(poster=(19, 14), tile=21, padding=1),
)
"""The mockup's tiles, and smaller ones that fit beside the poster panel on a screen of
100 columns; the largest that fits is used."""


def tile_size(room: int) -> TileSize | None:
    """The largest tiles whose dialog fits in ``room`` columns, or ``None``."""
    return next((size for size in TILE_SIZES if size.dialog_width <= room), None)


@dataclass(frozen=True, slots=True)
class Picked:
    """What the person chose: ``match``, from the Candidates the search ``found``."""

    match: Candidate
    found: tuple[Candidate, ...]


def picker_choices(current: Candidate | None, found: Sequence[Candidate]) -> tuple[Candidate, ...]:
    """The Candidates the picker lists: the current Match, then the first one found that
    is not it; with no current Match, the first two found. No Match is listed twice."""
    if current is None:
        return tuple(found[:_CANDIDATE_ROWS])
    others = (c for c in found if c.id != current.id)
    return (current, *tuple(others)[:1])


def candidate_text(candidate: Candidate) -> str:
    """A Candidate as the picker writes it: its name, and its year when known."""
    return f"{candidate.name} ({candidate.year})" if candidate.year is not None else candidate.name


def _year_text(candidate: Candidate, *, current: bool) -> str:
    """The line under a tile's name: the year when known, and "(current)" for the
    current Match."""
    parts = [f"({candidate.year})"] if candidate.year is not None else []
    if current:
        parts.append("(current)")
    return " ".join(parts)


class ChoiceRow(Horizontal):
    """One row of the picker: the selection mark, the row's key and what it offers.

    The row's children sit side by side: ``extra`` widgets follow the text, so a row
    can take one more widget, such as a Candidate's Poster.
    """

    DEFAULT_CSS = """
    ChoiceRow {
        height: 1;
        margin-bottom: 1;
    }
    ChoiceRow.-selected {
        background: $tr-highlight;
    }
    ChoiceRow .choice-mark {
        width: 2;
        color: $accent;
    }
    ChoiceRow .choice-key {
        width: 4;
        color: $accent;
        text-style: bold;
    }
    ChoiceRow .choice-text {
        width: 1fr;
    }
    ChoiceRow.-selected .choice-text {
        text-style: bold;
    }
    """

    def __init__(self, key: str, text: str, *extra: Widget, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._key = key
        self._text = text
        self._extra = extra

    def compose(self) -> ComposeResult:
        yield Static("", classes="choice-mark")
        yield Static(Content(self._key), classes="choice-key")
        yield Static(Content(self._text), classes="choice-text")
        yield from self._extra

    def show(self, key: str, text: str, *, selected: bool) -> None:
        """Show the row's key and text, marked when it is the selected row."""
        self._key, self._text = key, text
        self.query_one(".choice-mark", Static).update("▸" if selected else "")
        self.query_one(".choice-key", Static).update(Content(key))
        self.query_one(".choice-text", Static).update(Content(text))
        self.set_class(selected, "-selected")


class PickerTile(Vertical):
    """One tile of the picker with Posters shown: a framed picture, then the name, the
    year and the tile's key under it.

    A Candidate's tile frames its Poster (:attr:`view`); the "type a title" tile frames
    ``typed``, the typing field, in its place, and has no :attr:`view`.
    """

    def __init__(
        self, key: str, size: TileSize, *, typed: Input | None = None, **kwargs: object
    ) -> None:
        super().__init__(classes="picker-tile", **kwargs)  # type: ignore[arg-type]
        self._key = key
        self._tile_size = size
        self._typed = typed
        self.styles.width = size.tile

    def compose(self) -> ComposeResult:
        width, height = self._tile_size.poster
        frame = Vertical(classes="tile-frame")
        frame.styles.width, frame.styles.height = width + 2, height + 2
        frame.styles.margin = (0, 0, 0, (self._tile_size.tile - width - 2) // 2)
        with frame:
            if self._typed is None:
                yield PosterView(cells=self._tile_size.poster)
            else:
                yield self._typed
                yield Static("type, then enter", classes="tile-help")
        yield Static("", classes="tile-name")
        yield Static("", classes="tile-year")
        yield Static(Content(self._key), classes="tile-key")

    @property
    def view(self) -> PosterView:
        """The tile's Poster (a Candidate's tile only)."""
        return self.query_one(PosterView)

    def show(self, name: str, year: str, *, selected: bool) -> None:
        """Show ``name`` and ``year`` under the picture, marked when it is selected."""
        self.query_one(".tile-name", Static).update(Content(name))
        self.query_one(".tile-year", Static).update(Content(year))
        self.set_class(selected, "-selected")


class _TypedTitle(Input):
    """The typing field. It takes focus only while the person types, so ``1`` to ``3``
    and ``/`` choose rows the rest of the time."""

    def __init__(self, value: str) -> None:
        super().__init__(value=value, placeholder="a title, then enter", id="picker-typed")
        self.can_focus = False

    def start(self) -> None:
        self.can_focus = True
        self.focus()
        self.cursor_position = len(self.value)

    def stop(self) -> None:
        self.can_focus = False
        self.blur()

    def on_click(self) -> None:
        self.screen.action_type()  # type: ignore[attr-defined]


class MatchPicker(ModalScreen[Picked | None]):
    """ "Pick a match for <Title> · <Provider>": the Candidates, then "type a title".

    ``now`` is the line under the heading ("Now: …", "No match found." or what the
    file is). ``search`` runs a typed search; it is called off the screen's thread and
    raises :class:`~termrenamer.util.errors.ProviderError` on a failure. ``typed`` fills
    the typing field at the start; with ``typing``, the picker opens in it. ``posters``
    is where Posters come from while they are shown, and ``provider_id`` the Provider
    whose Poster references the Candidates carry; the app gives the picker a new
    source, or ``None``, with :meth:`use_posters` when a resize changes it.
    """

    AUTO_FOCUS = None
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
        Binding("left", "move_across(-1)", show=False),
        Binding("right", "move_across(1)", show=False),
        Binding("enter", "choose", show=False),
        Binding("slash", "type", show=False),
        Binding("escape", "close", show=False),
        *(Binding(str(n), f"choose({n - 1})", show=False) for n in range(1, 4)),
    ]

    DEFAULT_CSS = """
    MatchPicker {
        align: center middle;
        background: $background 60%;
    }
    MatchPicker #picker-dialog {
        width: 60;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        padding: 1 2 0 2;
        border: double $accent;
        border-title-color: $foreground;
        border-title-style: bold;
        background: $tr-dialog;
    }
    MatchPicker #picker-now {
        color: $tr-dim;
        margin: 0 1 1 1;
    }
    MatchPicker #picker-rows {
        height: auto;
    }
    MatchPicker #picker-type .choice-text {
        width: auto;
        margin-right: 1;
    }
    MatchPicker #picker-typed {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
        background: $tr-field;
    }
    MatchPicker #picker-typed:focus {
        border: none;
    }
    MatchPicker #picker-status {
        height: auto;
        margin: 0 1 1 1;
    }
    MatchPicker #picker-hint {
        color: $tr-dim;
        margin: 0 1 1 1;
    }
    MatchPicker #picker-dialog.-tiles #picker-status {
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    MatchPicker #picker-tiles {
        height: auto;
        margin-bottom: 1;
    }
    MatchPicker .picker-tile {
        height: auto;
        margin-right: 1;
    }
    MatchPicker #picker-tile-type {
        margin-right: 0;
    }
    MatchPicker .tile-frame {
        border: solid $tr-line;
        align: center middle;
    }
    MatchPicker .picker-tile.-selected .tile-frame {
        border: heavy $accent;
    }
    MatchPicker .tile-frame #picker-typed {
        width: 1fr;
        margin: 0 1;
    }
    MatchPicker .tile-help {
        width: 100%;
        margin-top: 1;
        color: $tr-dim;
        text-align: center;
    }
    MatchPicker .tile-name, MatchPicker .tile-year, MatchPicker .tile-key {
        width: 100%;
        height: 1;
        text-align: center;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    MatchPicker .tile-name {
        margin-top: 1;
        color: $tr-dim;
    }
    MatchPicker .picker-tile.-selected .tile-name {
        color: $foreground;
        text-style: bold;
    }
    MatchPicker .tile-year {
        color: $tr-dim;
    }
    MatchPicker .tile-key {
        color: $accent;
    }
    """

    def __init__(
        self,
        *,
        heading: str,
        now: str,
        current: Candidate | None,
        found: Sequence[Candidate],
        search: Callable[[str], tuple[Candidate, ...]],
        typed: str = "",
        typing: bool = False,
        posters: PosterSource | None = None,
        provider_id: str | None = None,
    ) -> None:
        super().__init__()
        self._heading = heading
        self._now = now
        self._current = current
        self._found = tuple(found)
        self._search = search
        self._typed = typed
        self._start_typing = typing
        self._selected = 0
        self._searching: Worker[tuple[Candidate, ...]] | None = None
        self._searching_text = ""
        self._source = posters
        self._provider_id = provider_id
        self._tile_size: TileSize | None = None
        """The tiles' size while they are shown, or ``None`` for the plain list."""
        self._status = ("", "$tr-dim")

    @property
    def choices(self) -> tuple[Candidate, ...]:
        """The Candidates listed now, in their order."""
        return picker_choices(self._current, self._found)

    @property
    def typing(self) -> bool:
        """Whether the typing field has the keys."""
        return self.query_one("#picker-typed", _TypedTitle).has_focus

    def compose(self) -> ComposeResult:
        self._tile_size = self._wanted_size()
        with Vertical(id="picker-dialog"):
            yield Static(Content(self._now), id="picker-now")
            if self._tile_size is None:
                with Vertical(id="picker-rows"):
                    for index in range(_CANDIDATE_ROWS):
                        yield ChoiceRow(str(index + 1), "", id=f"picker-choice-{index}")
                    yield ChoiceRow("/", "Type a title", _TypedTitle(self._typed), id="picker-type")
            else:
                with Horizontal(id="picker-tiles"):
                    for index in range(_CANDIDATE_ROWS):
                        yield PickerTile(str(index + 1), self._tile_size, id=f"picker-tile-{index}")
                    yield PickerTile(
                        "/", self._tile_size, typed=_TypedTitle(self._typed), id="picker-tile-type"
                    )
            yield Static("", id="picker-status")
            yield Static("", id="picker-hint")

    def on_mount(self) -> None:
        self._dress(typing=self._start_typing)

    async def on_resize(self) -> None:
        await self._lay_out()

    def use_posters(self, source: PosterSource | None) -> None:
        """Show Posters from ``source``, or the plain list for ``None``: the app calls
        this when the screen's size changes whether Posters show."""
        if source is self._source:
            return
        self._source = source
        if self.is_mounted:
            for view in self.query(PosterView):
                view.use(source)
            self.call_later(self._lay_out)

    def dismiss(self, result: Picked | None = None) -> AwaitComplete:
        self._clear_posters()
        return super().dismiss(result)

    def _clear_posters(self) -> None:
        """Clear each tile's image before the tiles go, so the image package takes it
        off the terminal; removing an image widget alone leaves a Kitty image behind."""
        for view in self.query(PosterView):
            view.use(None)

    def _wanted_size(self) -> TileSize | None:
        if self._source is None:
            return None
        return tile_size(room_beside_posters(self.app))

    async def _lay_out(self) -> None:
        """Change between the tiles and the list, or the tiles' size, when the screen or
        the Posters ask for it; keep what was typed and the status line."""
        if self._wanted_size() == self._tile_size:
            keep_clear_of_posters(self.query_one("#picker-dialog"))
            return
        typed = self.query_one("#picker-typed", _TypedTitle)
        self._typed, typing = typed.value, typed.has_focus
        self._clear_posters()
        await self.recompose()
        self._dress(typing=typing)

    def _dress(self, *, typing: bool) -> None:
        """Set up what compose left: the heading, the place, the status line, the
        Posters, the typing field and the rows."""
        dialog = self.query_one("#picker-dialog")
        dialog.border_title = Content(f" {self._heading} ")
        size = self._tile_size
        dialog.set_class(size is not None, "-tiles")
        if size is not None:
            dialog.styles.width = size.dialog_width
            dialog.styles.padding = (1, size.padding, 0, size.padding)
        keep_clear_of_posters(dialog)
        self._say(*self._status)
        for view in self.query(PosterView):
            view.use(self._source)
        if typing:
            self.action_type()
        self._show_rows()

    def _request(self, candidate: Candidate) -> PosterRequest | None:
        if candidate.poster_ref and self._provider_id:
            return PosterRequest(self._provider_id, candidate.poster_ref)
        return None

    def _show_rows(self) -> None:
        choices = self.choices
        rows = len(choices) + 1
        self._selected = max(0, min(self._selected, rows - 1))
        keys = f"1-{rows}" if rows > 1 else "1"
        arrows, typing = ("←→", "type a title") if self._tile_size else ("↑↓", "type")
        self.query_one("#picker-hint", Static).update(
            f"{arrows} choose · {keys} or enter use it · / {typing} · esc close"
        )
        if self._tile_size is not None:
            self._show_tiles(choices)
            return
        for index in range(_CANDIDATE_ROWS):
            row = self.query_one(f"#picker-choice-{index}", ChoiceRow)
            row.display = index < len(choices)
            if index < len(choices):
                text = candidate_text(choices[index])
                if choices[index] == self._current:
                    text += " (current)"
                row.show(str(index + 1), text, selected=index == self._selected)
        self.query_one("#picker-type", ChoiceRow).show(
            "/", "Type a title", selected=self._selected == len(choices)
        )

    def _show_tiles(self, choices: tuple[Candidate, ...]) -> None:
        for index in range(_CANDIDATE_ROWS):
            tile = self.query_one(f"#picker-tile-{index}", PickerTile)
            tile.display = index < len(choices)
            if index >= len(choices):
                tile.view.clear()
                continue
            candidate = choices[index]
            year = _year_text(candidate, current=candidate == self._current)
            tile.show(candidate.name, year, selected=index == self._selected)
            tile.view.show(candidate.name, self._request(candidate), download=True)
        self.query_one("#picker-tile-type", PickerTile).show(
            "Type a title", "", selected=self._selected == len(choices)
        )

    def _say(self, text: str, colour: str = "$tr-dim") -> None:
        """Show ``text`` on the picker's status line; no text hides the line."""
        self._status = (text, colour)
        status = self.query_one("#picker-status", Static)
        status.update(Content.from_markup(f"[{colour}]$text[/]", text=text))
        status.display = bool(text)

    # ------------------------------------------------------------------ keys

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # ``←`` ``→`` move between tiles; the plain list has no use for them.
        return action != "move_across" or self._tile_size is not None

    def action_move_across(self, step: int) -> None:
        """``←`` ``→``: as ``↑`` ``↓``, while the tiles show (see :meth:`check_action`)."""
        self.action_move(step)

    def action_move(self, step: int) -> None:
        self.query_one("#picker-typed", _TypedTitle).stop()
        self._selected = max(0, min(self._selected + step, len(self.choices)))
        self._show_rows()

    def action_choose(self, index: int | None = None) -> None:
        """Use the row ``index`` (from ``0``), or the selected row: a Candidate is picked,
        the "type a title" row goes to typing."""
        choices = self.choices
        if index is None:
            index = self._selected
        if index > len(choices):
            return
        if index == len(choices):
            self._selected = index
            self.action_type()
            self._show_rows()
            return
        self.dismiss(Picked(match=choices[index], found=self._found))

    def action_type(self) -> None:
        self._selected = len(self.choices)
        self.query_one("#picker-typed", _TypedTitle).start()
        self._show_rows()

    def action_close(self) -> None:
        self.dismiss(None)

    # ---------------------------------------------------------- the search

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if not text:
            self._say("Type a title to search for.", "$warning")
            return
        if self._searching is not None:
            return
        self._say(f"Searching for “{text}”…")
        self._searching_text = text
        self._searching = self.run_worker(
            lambda: self._search(text),
            thread=True,
            exit_on_error=False,
            name="picker-search",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._searching:
            return
        if event.state is WorkerState.SUCCESS:
            self._searching = None
            self._found = event.worker.result or ()
            text = self._searching_text
            if self._found:
                self._say("")
                self.query_one("#picker-typed", _TypedTitle).stop()
                # The first Candidate the search added.
                self._selected = 1 if self._current is not None else 0
                if not any(c != self._current for c in self.choices):
                    self._selected = len(self.choices)
                    self._say(f"Only the current Match was found for “{text}”.")
            else:
                self._say(f"Nothing found for “{text}”.", "$warning")
            self._show_rows()
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            self._searching = None
            error = event.worker.error
            if isinstance(error, ProviderError):
                message = f"{error} Nothing changed."
            else:
                message = f"The search failed: {error}"
            _LOG.warning(message)
            self._say(message, "$error")
