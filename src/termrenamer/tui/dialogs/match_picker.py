"""The Match picker: pick a different Match for a Title, or type a title to search again.

It lists the current Match first (marked), then the first of the search's results
that is not the current Match, then the "type a title" row, as a plain list. With
no current Match it lists the first two results. ``↑`` ``↓`` move, ``1`` to ``3`` or
``enter`` choose, ``/`` goes to typing, and Escape closes it with nothing picked.

Typing a title and pressing ``enter`` searches the Provider again, off the screen's
thread; the results replace the Candidates listed. The picker returns a
:class:`Picked` or ``None``; it never changes the Plan itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from termrenamer.core.models import Candidate
from termrenamer.util.errors import ProviderError

_LOG = logging.getLogger("termrenamer.tui")

_CANDIDATE_ROWS = 2
"""At most two Candidates are listed at once; typing a more exact title reaches others."""


@dataclass(frozen=True, slots=True)
class Picked:
    """What the person chose: ``match``, from the search results ``found``."""

    match: Candidate
    found: tuple[Candidate, ...]


def picker_choices(current: Candidate | None, found: Sequence[Candidate]) -> tuple[Candidate, ...]:
    """The Candidates the picker lists: the current Match, then the first result that is
    not it; with no current Match, the first two results. No Match is listed twice."""
    if current is None:
        return tuple(found[:_CANDIDATE_ROWS])
    others = (c for c in found if c.id != current.id)
    return (current, *tuple(others)[:1])


def candidate_text(candidate: Candidate) -> str:
    """A Candidate as the picker writes it: its name, and its year when known."""
    return f"{candidate.name} ({candidate.year})" if candidate.year is not None else candidate.name


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
        yield Static(escape(self._key), classes="choice-key")
        yield Static(escape(self._text), classes="choice-text")
        yield from self._extra

    def show(self, key: str, text: str, *, selected: bool) -> None:
        """Show the row's key and text, marked when it is the selected row."""
        self._key, self._text = key, text
        self.query_one(".choice-mark", Static).update("▸" if selected else "")
        self.query_one(".choice-key", Static).update(escape(key))
        self.query_one(".choice-text", Static).update(escape(text))
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
    the typing field at the start; with ``typing``, the picker opens in it.
    """

    AUTO_FOCUS = None
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
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

    @property
    def choices(self) -> tuple[Candidate, ...]:
        """The Candidates listed now, in their order."""
        return picker_choices(self._current, self._found)

    @property
    def typing(self) -> bool:
        """Whether the typing field has the keys."""
        return self.query_one("#picker-typed", _TypedTitle).has_focus

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Static(escape(self._now), id="picker-now")
            with Vertical(id="picker-rows"):
                for index in range(_CANDIDATE_ROWS):
                    yield ChoiceRow(str(index + 1), "", id=f"picker-choice-{index}")
                yield ChoiceRow("/", "Type a title", _TypedTitle(self._typed), id="picker-type")
            yield Static("", id="picker-status")
            yield Static("↑↓ choose · 1-3 or enter use it · / type · esc close", id="picker-hint")

    def on_mount(self) -> None:
        self.query_one("#picker-dialog").border_title = f" {escape(self._heading)} "
        self._say("")
        if self._start_typing:
            self.action_type()
        self._show_rows()

    def _show_rows(self) -> None:
        choices = self.choices
        rows = len(choices) + 1
        self._selected = max(0, min(self._selected, rows - 1))
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
        keys = f"1-{rows}" if rows > 1 else "1"
        self.query_one("#picker-hint", Static).update(
            f"↑↓ choose · {keys} or enter use it · / type · esc close"
        )

    def _say(self, text: str, colour: str = "$tr-dim") -> None:
        """Show ``text`` on the picker's status line; no text hides the line."""
        status = self.query_one("#picker-status", Static)
        status.update(f"[{colour}]{escape(text)}[/]")
        status.display = bool(text)

    # ------------------------------------------------------------------ keys

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
