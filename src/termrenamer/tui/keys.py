"""The key table: every key of the screen, the one place the keys, footer and Help come from.

Each :class:`Key` names its actions. When a key is pressed on the main screen, the
app runs the action on the current Stage's view, or failing that on the app itself.
A key whose action nothing implements yet does nothing and is left out of the footer,
but Help lists every key. So a ticket that builds a key's action adds a method
``action_<name>`` to its Stage or to the app, and does not edit this table.

Order matters twice: the footer lists a Stage's keys in this order, and a key pressed
runs the first entry for that key whose Stages hold the current one.

When the footer is too narrow for every key that works, it drops hints by
:func:`drop_rank` until the rest fit: first the keys of :data:`DROPPED_FIRST`, in that
order, then the selection keys, then the Stage's own keys from the last listed. Help
is never dropped, as it lists every key.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from textual.binding import Binding, BindingType

from termrenamer.tui.stage import Stage

_ALL = frozenset(Stage)


@dataclass(frozen=True, slots=True)
class Key:
    """One row of the key table.

    ``display`` is the key as the footer and Help write it. ``bindings`` pairs each
    Textual key name with the action it runs. ``hint`` is the footer's label and
    ``help_text`` the Help text. ``stages`` are the Stages the key works at; ``anywhere``
    keys also work in the views (Settings, Logs, Help). ``guarded`` names what the
    lock refuses while a Plan is being built or applied (such as "Mode"), so the key
    gives the lock's message there. ``place`` says where a key that works at no Stage
    works, such as in dialogs.
    """

    display: str
    bindings: tuple[tuple[str, str], ...]
    hint: str
    help_text: str
    stages: frozenset[Stage]
    anywhere: bool = False
    guarded: str | None = None
    place: str | None = None

    @property
    def stage_names(self) -> tuple[str, ...]:
        """The names of the key's Stages, in the Stages' order."""
        return tuple(stage.value for stage in Stage if stage in self.stages)

    @property
    def where(self) -> str:
        """Where the key works, as Help writes it: "Any", or its Stages."""
        if self.place is not None:
            return self.place
        if self.stages == _ALL:
            return "Any"
        return ", ".join(self.stage_names)


DROPPED_FIRST = (
    "toggle_posters",
    "open_logs",
    "change_provider",
    "change_mode",
    "open_settings",
    "quit",
)
"""The actions whose hints a narrow footer drops first, in this order: each works at
every Stage it is listed, and Help names it."""

SELECTION = ("select_previous", "previous_file")
"""The selection keys' first actions, ``↑↓`` then ``←→``, dropped after
:data:`DROPPED_FIRST`."""

NEVER_DROPPED = "open_help"
"""Help's action: its hint stays however narrow the footer is."""


def drop_rank(key: Key, position: int) -> tuple[int, int] | None:
    """When a narrow footer drops ``key``, the ``position``-th hint it lists: the lower
    rank goes first, and ``None`` is never."""
    action = key.bindings[0][1] if key.bindings else ""
    if action == NEVER_DROPPED:
        return None
    if action in DROPPED_FIRST:
        return (0, DROPPED_FIRST.index(action))
    if action in SELECTION:
        return (1, SELECTION.index(action))
    return (2, -position)  # the Stage's own keys, the last listed first


def _bound(key: str, action: str) -> tuple[tuple[str, str], ...]:
    return ((key, action),)


_UP_DOWN = (("up", "select_previous"), ("down", "select_next"))

KEYS: tuple[Key, ...] = (
    Key("↑↓", _UP_DOWN, "Source", "Select a Source", frozenset({Stage.QUEUE})),
    Key("↑↓", _UP_DOWN, "Select", "Select a Title", frozenset({Stage.PLAN, Stage.PREVIEW})),
    Key(
        "←→",
        (("left", "previous_file"), ("right", "next_file")),
        "File",
        "Select a file of the Title",
        frozenset({Stage.PREVIEW}),
    ),
    Key("b", _bound("b", "build_plan"), "Build Plan", "Build the Plan", frozenset({Stage.QUEUE})),
    Key(
        "enter",
        _bound("enter", "apply"),
        "Apply…",
        "Apply, then y or enter to confirm, n or esc to go back",
        frozenset({Stage.PREVIEW}),
    ),
    Key(
        "t",
        _bound("t", "pick_match"),
        "Match",
        "Open the Match picker (↑↓, 1 to 3, enter, / to type, esc)",
        frozenset({Stage.PREVIEW}),
    ),
    Key(
        "x",
        _bound("x", "leave_out"),
        "Leave out",
        "Leave the file out, or put it back",
        frozenset({Stage.PREVIEW}),
    ),
    Key("u", _bound("u", "undo"), "Undo", "Undo, then y or n", frozenset({Stage.APPLIED})),
    Key("n", _bound("n", "new_batch"), "New batch", "New batch", frozenset({Stage.APPLIED})),
    Key("a", _bound("a", "add_file"), "Add file", "Add a file", frozenset({Stage.QUEUE})),
    Key("f", _bound("f", "add_folder"), "Add folder", "Add a folder", frozenset({Stage.QUEUE})),
    Key(
        "c", _bound("c", "clear_queue"), "Clear queue", "Clear the queue", frozenset({Stage.QUEUE})
    ),
    Key("i", _bound("i", "toggle_posters"), "Poster", "Hide or show Posters", _ALL, anywhere=True),
    Key(
        "m",
        _bound("m", "change_mode"),
        "Mode",
        "Change Mode",
        frozenset({Stage.QUEUE, Stage.PREVIEW}),
        guarded="Mode",
    ),
    Key(
        "p",
        _bound("p", "change_provider"),
        "Provider",
        "Change Provider",
        frozenset({Stage.QUEUE, Stage.PREVIEW}),
        guarded="Provider",
    ),
    Key(
        "esc",
        _bound("escape", "cancel_build"),
        "Cancel Plan",
        "Cancel the build",
        frozenset({Stage.PLAN}),
    ),
    Key(
        "esc",
        _bound("escape", "discard_plan"),
        "Discard Plan",
        "Discard the Plan",
        frozenset({Stage.PREVIEW}),
    ),
    Key("esc", (), "Close", "Close a dialog or view", frozenset(), place="Dialogs, views"),
    Key(
        "s",
        _bound("s", "open_settings"),
        "Settings",
        "Settings (↑↓, enter or space, esc)",
        frozenset({Stage.QUEUE, Stage.PREVIEW, Stage.APPLIED}),
        guarded="Settings",
    ),
    Key("l", _bound("l", "open_logs"), "Logs", "Logs", _ALL, anywhere=True),
    Key("?", _bound("question_mark", "open_help"), "Help", "Help", _ALL, anywhere=True),
    Key("q", _bound("q", "quit"), "Quit", "Quit", _ALL, anywhere=True),
)
"""Every key of the screen, in footer order."""


def bindings() -> list[BindingType]:
    """One hidden app binding per Textual key of the table, each running ``press('<key>')``."""
    seen = dict.fromkeys(name for key in KEYS for name, _action in key.bindings)
    return [Binding(name, f"press('{name}')", show=False) for name in seen]


def entries_for(name: str) -> Iterator[tuple[Key, str]]:
    """Each table row bound to the Textual key ``name``, with the action it runs there."""
    for key in KEYS:
        for bound, action in key.bindings:
            if bound == name:
                yield key, action


VIEW_HINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "settings": (
        ("↑↓", "Move"),
        ("enter", "Edit or toggle"),
        ("esc", "Close"),
        ("?", "Help"),
        ("q", "Quit"),
    ),
    "logs": (("esc", "Close"), ("?", "Help"), ("q", "Quit")),
    "help": (("esc", "Close"), ("l", "Logs"), ("q", "Quit")),
}
"""The hint line of each view (Settings, Logs, Help): each key and its label."""
