"""The key table: every key of the screen, the one place the keys, footer and Help come from.

Each :class:`Key` names its actions. When a key is pressed on the main screen, the
app runs the action on the current Stage's view, or failing that on the app itself.
A key whose action nothing implements yet does nothing and is left out of the footer,
but Help lists every key. So a ticket that builds a key's action adds a method
``action_<name>`` to its Stage or to the app, and does not edit this table.

Order matters twice: the footer lists a Stage's keys in this order, and a key pressed
runs the first entry for that key whose Stages hold the current one.
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
    ``what`` the Help text; ``where`` says in Help where it works. ``stages`` are the
    Stages the key works at; ``anywhere`` keys also work in the views (Settings, Logs,
    Help). ``guarded`` names what the lock refuses while a Plan is being built or
    applied (such as "Mode"), so the key gives the lock's message there.
    """

    display: str
    bindings: tuple[tuple[str, str], ...]
    hint: str
    what: str
    where: str
    stages: frozenset[Stage]
    anywhere: bool = False
    guarded: str | None = None


def _one(key: str, action: str) -> tuple[tuple[str, str], ...]:
    return ((key, action),)


_UP_DOWN = (("up", "select_previous"), ("down", "select_next"))

KEYS: tuple[Key, ...] = (
    Key("↑↓", _UP_DOWN, "Source", "Select a Source", "Queue", frozenset({Stage.QUEUE})),
    Key(
        "↑↓",
        _UP_DOWN,
        "Select",
        "Select a Title",
        "Plan, Preview",
        frozenset({Stage.PLAN, Stage.PREVIEW}),
    ),
    Key(
        "←→",
        (("left", "previous_file"), ("right", "next_file")),
        "File",
        "Select a file of the Title",
        "Plan, Preview",
        frozenset({Stage.PLAN, Stage.PREVIEW}),
    ),
    Key(
        "b",
        _one("b", "build_plan"),
        "Build Plan",
        "Build the Plan",
        "Queue",
        frozenset({Stage.QUEUE}),
    ),
    Key(
        "enter",
        _one("enter", "apply"),
        "Apply…",
        "Apply, then y or enter to confirm, n or esc to go back",
        "Preview",
        frozenset({Stage.PREVIEW}),
    ),
    Key(
        "t",
        _one("t", "pick_match"),
        "Match",
        "Open the Match picker (←→, 1 to 3, enter, / to type, esc)",
        "Preview",
        frozenset({Stage.PREVIEW}),
    ),
    Key(
        "x",
        _one("x", "leave_out"),
        "Leave out",
        "Leave the file out, or put it back",
        "Preview",
        frozenset({Stage.PREVIEW}),
    ),
    Key("u", _one("u", "undo"), "Undo", "Undo, then y or n", "Applied", frozenset({Stage.APPLIED})),
    Key(
        "n", _one("n", "new_batch"), "New batch", "New batch", "Applied", frozenset({Stage.APPLIED})
    ),
    Key("a", _one("a", "add_file"), "Add file", "Add a file", "Queue", frozenset({Stage.QUEUE})),
    Key(
        "f",
        _one("f", "add_folder"),
        "Add folder",
        "Add a folder",
        "Queue",
        frozenset({Stage.QUEUE}),
    ),
    Key(
        "c",
        _one("c", "clear_queue"),
        "Clear queue",
        "Clear the queue",
        "Queue",
        frozenset({Stage.QUEUE}),
    ),
    Key(
        "i",
        _one("i", "toggle_posters"),
        "Poster",
        "Hide or show Posters",
        "Any",
        _ALL,
        anywhere=True,
    ),
    Key(
        "m",
        _one("m", "change_mode"),
        "Mode",
        "Change Mode",
        "Queue, Preview",
        frozenset({Stage.QUEUE, Stage.PREVIEW}),
        guarded="Mode",
    ),
    Key(
        "p",
        _one("p", "change_provider"),
        "Provider",
        "Change Provider",
        "Queue, Preview",
        frozenset({Stage.QUEUE, Stage.PREVIEW}),
        guarded="Provider",
    ),
    Key(
        "esc",
        _one("escape", "cancel_build"),
        "Cancel Plan",
        "Cancel the build",
        "Plan",
        frozenset({Stage.PLAN}),
    ),
    Key(
        "esc",
        _one("escape", "discard_plan"),
        "Discard Plan",
        "Discard the Plan",
        "Preview",
        frozenset({Stage.PREVIEW}),
    ),
    Key("esc", (), "Close", "Close a dialog or view", "Dialogs, views", frozenset()),
    Key(
        "s",
        _one("s", "open_settings"),
        "Settings",
        "Settings (↑↓, enter or space, esc)",
        "Queue, Preview, Applied",
        frozenset({Stage.QUEUE, Stage.PREVIEW, Stage.APPLIED}),
        guarded="Settings",
    ),
    Key("l", _one("l", "open_logs"), "Logs", "Logs", "Any", _ALL, anywhere=True),
    Key("?", _one("question_mark", "open_help"), "Help", "Help", "Any", _ALL, anywhere=True),
    Key("q", _one("q", "quit"), "Quit", "Quit", "Any", _ALL, anywhere=True),
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
