"""Apply's checks of a source sit directly before the call they guard: another program
that changes the source before any other call Apply makes on the disk never makes Apply
remove a file's last name, or another program's file. Apply cannot defend against a
change between its last look and the very next call, so that one moment is left out:
each test runs the change before every call Apply makes but the one right after a look
at the old name."""

from __future__ import annotations

import errno
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyOutcome, Plan, UndoOutcome
from termrenamer.core.planning import plan_queue
from termrenamer.core.undo import undo_apply

from .test_plan_stragglers import _options, _provider, _write

WINDOWS = os.name == "nt"
# Another program's own calls, never counted, refused or failed by a test's patches.
_UNLINK, _RENAME = os.unlink, os.rename

MINE = b"my episode"
THEIRS = b"another program's file"

# Every call on the disk Apply and Undo make through ``os``.
_CALLS = (
    "lstat",
    "stat",
    "fstat",
    "open",
    "close",
    "read",
    "write",
    "fsync",
    "chmod",
    "utime",
    "link",
    "unlink",
    "rename",
    "symlink",
    "readlink",
    "mkdir",
    "rmdir",
    "listdir",
    "scandir",
)


@dataclass
class _Disk:
    """Counts each call on the disk, and runs ``change`` once just before call
    ``before`` (counted from 0). Only a call after the first call ``after`` is chosen,
    and never one made just after an ``lstat`` of ``old``: a change there is the moment
    Apply cannot defend."""

    old: Path
    change: Callable[[], None]
    before: int | None = None
    after: tuple[str, str] | None = None
    started: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)
    open_to_change: list[int] = field(default_factory=list)
    busy: bool = False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _CALLS:
            monkeypatch.setattr(os, name, self._traced(name, getattr(os, name)))

    def _traced(self, name: str, real: Callable[..., object]) -> Callable[..., object]:
        def call(*args: object, **kwargs: object) -> object:
            if self.busy:
                return real(*args, **kwargs)
            first = args[0] if args else None
            where = "" if first is None or isinstance(first, int) else os.fspath(first)  # type: ignore[call-overload]
            k = len(self.calls)
            after_a_look = bool(self.calls) and self.calls[-1] == ("lstat", str(self.old))
            self.started = self.started or self.after is None or self.after in self.calls
            open_to_change = self.started and not after_a_look
            if open_to_change:
                self.open_to_change.append(k)
            if k == self.before and open_to_change:
                self.busy = True
                try:
                    self.change()
                finally:
                    self.busy = False
            self.calls.append((name, where))
            return real(*args, **kwargs)

        return call


@dataclass(frozen=True)
class _Near:
    """Call ``k``, which a change came before, shown with the calls around it."""

    k: int
    calls: list[tuple[str, str]]

    def __str__(self) -> str:
        near = self.calls[max(0, self.k - 3) : self.k + 2]
        return f"{self.k}: " + ", ".join(f"{n}({Path(w).name})" for n, w in near)


@dataclass(frozen=True)
class _Case:
    """One move under test: the file's old name and new name, and what runs it."""

    old: Path
    new: Path
    run: Callable[[], ApplyOutcome | UndoOutcome]


def _a_move(tmp_path: Path, side: str) -> _Case:
    """A video planned into a Destination root; with ``side`` ``"undo"``, moved there by
    Apply, and Undo's move back is the move under test."""
    video = _write(tmp_path / "Backups" / "Show.Name.S01E01.mkv", MINE)
    root = tmp_path / "Library"
    root.mkdir()
    plan: Plan = plan_queue([video], _options(destination_root=root), _provider()).plan
    dest = plan.entries[0].destination
    assert dest is not None
    if side == "apply":
        return _Case(video, dest, lambda: apply_plan(plan, confirmed=True))
    outcome = apply_plan(plan, confirmed=True)
    assert dest.read_bytes() == MINE
    return _Case(dest, video, lambda: undo_apply(outcome))


def _across_drives(monkeypatch: pytest.MonkeyPatch, old: Path) -> None:
    """The move of ``old`` takes the copy path, as to another drive."""
    real_link, real_rename = os.link, os.rename

    def no_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if os.fspath(src) == str(old):  # type: ignore[call-overload]
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    def rename(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if os.fspath(src) == str(old):  # type: ignore[call-overload]
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_rename(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "rename", rename)


def _unlink_fails(monkeypatch: pytest.MonkeyPatch, old: Path) -> None:
    """Removing the old name fails, as on a file another program holds open."""
    real_unlink = os.unlink

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        if os.fspath(path) == str(old):  # type: ignore[call-overload]
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", unlink)


def _skip_the_hard_link_on_windows(path_name: str) -> None:
    if WINDOWS and path_name == "link":
        pytest.skip("a Windows move makes no hard link: its rename leaves no second name")


def _runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    side: str,
    path_name: str,
    *,
    unlink_fails: bool,
    change: Callable[[_Case, list[str]], None],
) -> list[tuple[_Near, _Case, ApplyOutcome | UndoOutcome, list[str]]]:
    """Run the move once to count its calls, then once more for each call that a change
    may come before, with ``change`` made just before it; return each run. With
    ``unlink_fails``, the removal of the old name fails, and only the calls after it
    are changed before: the recovery from that failure."""

    def one(k: int | None) -> tuple[_Case, ApplyOutcome | UndoOutcome, list[str], _Disk]:
        case = _a_move(tmp_path / f"run {k}", side)
        notes: list[str] = []
        after = ("unlink", str(case.old)) if unlink_fails else None
        disk = _Disk(old=case.old, change=lambda: change(case, notes), before=k, after=after)
        with monkeypatch.context() as m:
            if path_name == "copy EXDEV":
                _across_drives(m, case.old)
            if unlink_fails:
                _unlink_fails(m, case.old)
            disk.install(m)
            outcome = case.run()
        return case, outcome, notes, disk

    _, _, _, counted = one(None)
    runs = []
    for k in counted.open_to_change:
        case, outcome, notes, disk = one(k)
        runs.append((_Near(k, disk.calls), case, outcome, notes))
    assert runs
    return runs


def _removes_old(case: _Case, notes: list[str]) -> None:
    """Another program removes the old name; Windows refuses while Apply holds it open.
    Once Apply has removed the new name again, the old name is the file's only one, and
    removing it deletes the file whatever Apply does."""
    if not case.new.exists(follow_symlinks=False):
        notes.append("its only name")
    try:
        _UNLINK(case.old)
    except FileNotFoundError:
        notes.append("gone")
    except PermissionError:
        notes.append("refused")


def _replaces_old(case: _Case, notes: list[str]) -> None:
    """Another program renames the file at the old name away and writes its own file
    there; Windows refuses the rename while Apply holds the file open."""
    kept = case.old.with_name("kept by another program.mkv")
    try:
        _RENAME(case.old, kept)
    except FileNotFoundError:
        pass
    except PermissionError:
        notes.append("refused")
        return
    case.old.write_bytes(THEIRS)
    notes.append("replaced")


PATHS = ["link", "copy EXDEV"]
SIDES = ["apply", "undo"]


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("path_name", PATHS)
def test_a_failed_removal_of_the_old_name_never_loses_the_file_whatever_another_program_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, side: str, path_name: str
) -> None:
    _skip_the_hard_link_on_windows(path_name)
    runs = _runs(tmp_path, monkeypatch, side, path_name, unlink_fails=True, change=_removes_old)

    for k, case, outcome, notes in runs:
        if "its only name" in notes:
            continue
        at_old = case.old.exists(follow_symlinks=False)
        at_new = case.new.exists(follow_symlinks=False)
        assert at_old or at_new, f"the file is at neither name, change before call {k}"
        if at_new:
            assert case.new.read_bytes() == MINE, k
        if at_new and not at_old:
            moved = [(m.source, m.destination) for m in outcome.moves]
            told = (case.old, case.new) in moved or case.new in outcome.files_left_behind
            assert told, f"the file at its new name is not in the outcome, call {k}"


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("path_name", PATHS)
def test_another_programs_file_written_at_the_old_name_during_a_move_is_never_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, side: str, path_name: str
) -> None:
    _skip_the_hard_link_on_windows(path_name)
    runs = _runs(tmp_path, monkeypatch, side, path_name, unlink_fails=False, change=_replaces_old)

    for k, case, outcome, notes in runs:
        if "replaced" not in notes:
            continue
        assert case.old.read_bytes() == THEIRS, f"their file was removed, change before call {k}"
        kept = case.old.with_name("kept by another program.mkv")
        mine = [p for p in (case.new, kept) if p.exists() and p.read_bytes() == MINE]
        assert mine, f"the file is lost, change before call {k}"
        if case.new.exists():
            moved = [(m.source, m.destination) for m in outcome.moves]
            told = (case.old, case.new) in moved or case.new in outcome.files_left_behind
            assert told, f"the file at its new name is not in the outcome, call {k}"
