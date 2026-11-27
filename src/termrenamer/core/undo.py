"""Undo: put back what the last Apply moved, from its outcome alone (spec #16, section H).

Undo reads nothing to find what to put back: the outcome lists it. It works in this
order:

1. Each folder Apply removed is made again, each before the folders inside it.
2. Each move is put back, last move first. A file goes back only when it is still at its
   new place with the recorded size and modification time, read with ``lstat`` as the
   last call before the move, and only into a folder that is no link and lies behind
   none. The old name is claimed by the call that makes it
   (:func:`~termrenamer.core.moving.move_no_replace`), so nothing there is replaced;
   a case-only rename goes back as a plain rename.
3. Each folder Apply made is removed when Undo left it empty, each before its parent.

A file Apply left behind (a copy it could not remove) is left to the person: it is
never removed. An entry Apply found already at its name has no move and is not
touched. A folder is made again, and a file put back into a folder, only where no link
stands on the folder's path, so Undo never enters a link on the side of the old places:
the recorded old paths were resolved when the Sources were queued, so a link on them
came after. On the side of the new places Undo follows the recorded path, as Apply did:
a Destination root may itself lie behind a link.

Each change is recorded the moment its call succeeds. An error reading or moving a file
becomes that file's result; any other error stops Undo and leaves every later file
where it is, and the outcome so far is returned. Only an empty folder is ever removed,
so a folder a file still needs stays.

Like Apply, Undo cannot defend against another program that changes a file, a name or
a folder between Undo's last check and the call that follows it.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

from termrenamer.core.collisions import is_case_only_rename
from termrenamer.core.models import ApplyOutcome, ApplyResult, ApplyStatus, Move, UndoOutcome
from termrenamer.core.moving import (
    Changes,
    NotAsRecorded,
    is_folder,
    leave_folder,
    move_no_replace,
)

_LOG = logging.getLogger(__name__)

_STOPPED = "not put back: Undo stopped after an unexpected error"


def undo_apply(outcome: ApplyOutcome) -> UndoOutcome:
    """Reverse ``outcome``, the last Apply's, last move first, without replacing anything.

    Returns:
        One result per move of ``outcome``, every move Undo made, the folders it made
        again and removed, and any file it left behind.
    """
    changes = Changes()
    results: list[ApplyResult] = []
    stopped = False
    try:
        _make_folders_again(outcome.folders_removed, changes)
    except Exception:
        _LOG.exception("Undo stopped while making the removed folders again")
        stopped = True
    for move in reversed(outcome.moves):
        if stopped:
            results.append(_result(move, ApplyStatus.SKIP, _STOPPED))
            continue
        try:
            results.append(_put_back(move, changes))
        except Exception as exc:
            _LOG.error("Undo stopped at %s by an unexpected error", move.destination, exc_info=exc)
            results.append(_result(move, ApplyStatus.FAIL, f"unexpected error: {exc!r}"))
            stopped = True
    try:
        _remove_folders_made(outcome, changes)
    except Exception:
        _LOG.exception("Removing the folders Apply made stopped")
    return UndoOutcome(
        results=tuple(results),
        moves=tuple(changes.moves),
        folders_made_again=tuple(changes.folders_created),
        emptied_folders_removed=tuple(changes.folders_removed),
        files_left_behind=tuple(changes.files_left_behind),
    )


def _result(move: Move, status: ApplyStatus, reason: str) -> ApplyResult:
    """A result from the file's new place back to its old place."""
    return ApplyResult(
        source=move.destination, destination=move.source, status=status, reason=reason
    )


def _behind_a_link(folder: Path) -> bool:
    """Whether a link (a symbolic link or a junction) stands on ``folder``'s path: its
    resolved path differs from the recorded text."""
    return os.path.realpath(folder) != str(folder)


def _make_folders_again(removed: tuple[Path, ...], changes: Changes) -> None:
    """Make each folder of ``removed`` again, outer before inner; a folder that cannot be
    made, or whose parent is now a link or behind one, is logged, and the files bound
    for it are left where they are."""
    # Apply lists each folder before its parent; the stable sort keeps that order's
    # reverse wherever the depth is the same.
    for folder in sorted(reversed(removed), key=lambda path: len(path.parts)):
        if _behind_a_link(folder.parent):
            _LOG.warning("Undo did not make %s again: a link is now on its path", folder)
            continue
        try:
            os.mkdir(folder)
        except FileExistsError:
            continue  # something is there; a file bound for it goes in only if it is a folder
        except OSError as exc:
            _LOG.warning("Undo could not make %s again: %s", folder, exc)
            continue
        changes.folders_created.append(folder)


def _put_back(move: Move, changes: Changes) -> ApplyResult:
    """Move one file from its new place back to its old place, when the checks pass."""
    new, old = move.destination, move.source
    if is_case_only_rename(old, new):
        # The folder lists only the old name, as when Apply could not confirm a
        # case-only rename: the file is at its old place already, if it is as recorded.
        try:
            st = os.lstat(old)
        except OSError as exc:
            return _result(move, ApplyStatus.FAIL, f"cannot read its old place: {exc}")
        if (st.st_size, st.st_mtime_ns) != (move.fingerprint.size, move.fingerprint.mtime_ns):
            reason = "changed since Apply: its size or modification time changed"
            return _result(move, ApplyStatus.SKIP, reason)
        return _result(move, ApplyStatus.RENAMED, "already at its old place")
    linked = "its old folder is now a link or a file, or lies behind a link"
    if _behind_a_link(old.parent):
        return _result(move, ApplyStatus.SKIP, linked)
    try:
        folder = os.lstat(old.parent)
    except FileNotFoundError:
        return _result(move, ApplyStatus.SKIP, "its old folder no longer exists")
    except OSError as exc:
        return _result(move, ApplyStatus.FAIL, f"cannot read its old folder: {exc}")
    if not is_folder(old.parent, folder):
        return _result(move, ApplyStatus.SKIP, linked)
    try:
        move_no_replace(new, old, changes, expected=move.fingerprint)
    except FileExistsError:
        return _result(move, ApplyStatus.SKIP, "its old place is taken")
    except NotAsRecorded as exc:
        return _result(move, ApplyStatus.SKIP, f"changed since Apply: {exc.strerror}")
    except FileNotFoundError as exc:
        if not os.path.lexists(new):
            return _result(move, ApplyStatus.SKIP, "no longer at its new place")
        return _result(move, ApplyStatus.FAIL, f"could not be moved back: {exc}")
    except OSError as exc:
        return _result(move, ApplyStatus.FAIL, f"could not be moved back: {exc}")
    return _result(move, ApplyStatus.RENAMED, "ok")


def _remove_folders_made(outcome: ApplyOutcome, changes: Changes) -> None:
    """Remove each folder Apply made that Undo left empty, each before its parent.

    A folder that is, on this disk, one of the folders Apply removed (the same folder
    under another letter case, on a filesystem that ignores letter case) was there
    before Apply and stays.
    """
    were_there = []
    for folder in outcome.folders_removed:
        try:
            were_there.append(os.lstat(folder))
        except OSError:
            continue
    for folder in reversed(outcome.folders_created):
        try:
            st = os.lstat(folder)
            if not is_folder(folder, st) or any(os.path.samestat(st, w) for w in were_there):
                continue
            with os.scandir(folder) as entries:
                if any(True for _ in entries):
                    continue  # a file that stayed still needs it
            leave_folder(folder)
            os.rmdir(folder)
        except FileNotFoundError:
            continue
        except OSError as exc:
            if exc.errno != errno.ENOTEMPTY:
                _LOG.warning("Undo could not remove %s, which Apply made: %s", folder, exc)
            continue
        changes.folders_removed.append(folder)
