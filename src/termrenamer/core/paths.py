"""The path key that the queue, planning and Apply compare paths by."""

from __future__ import annotations

from pathlib import Path


def path_key(path: Path) -> str:
    """A path's key: its folder resolved, then its own name, case folded.

    The path's own name is not followed, so a symbolic link keys as itself and
    never stands in for its target. Two paths with the same key are the same
    file or folder, whatever the letter case; sorting by the key gives
    source-path order.
    """
    return str(path.parent.resolve() / path.name).casefold()


def recorded_key(path: Path) -> str:
    """The key of a path the Plan recorded: its text, case folded; no disk is read.

    The Plan records paths under resolved Sources and a resolved Destination root, so
    for them this matches :func:`path_key`. Working out a Plan's names and Stragglers
    compares paths by it, so deriving a Plan never reads a folder again.
    """
    return str(path).casefold()
