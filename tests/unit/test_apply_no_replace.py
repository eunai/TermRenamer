"""Apply's move refuses to replace anything at the destination, even something that
appears after the check and before the move, for entries and Stragglers alike."""

from __future__ import annotations

import errno
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from termrenamer.core import apply as apply_module
from termrenamer.core.apply import apply_plan
from termrenamer.core.collisions import name_is_taken
from termrenamer.core.models import ApplyResult, ApplyStatus, Plan
from termrenamer.core.paths import path_key
from termrenamer.core.planning import plan_queue

from .test_plan_stragglers import _options, _provider, _two_discs, _write

TAKEN = (ApplyStatus.SKIP, "destination exists at apply time")


def _appears_after_the_check(
    monkeypatch: pytest.MonkeyPatch, at: Path, make: Callable[[Path], None]
) -> None:
    """Make something appear at ``at`` right after Apply's check finds it free."""
    planted: list[Path] = []

    def check(path: Path, *, source: Path) -> bool:
        taken = name_is_taken(path, source=source)
        if path_key(path) == path_key(at) and not planted:
            make(at)
            planted.append(at)
        return taken

    monkeypatch.setattr(apply_module, "name_is_taken", check)


def _a_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"appeared")


def _a_folder(path: Path) -> None:
    path.mkdir(parents=True)


def _by_source(results: tuple[ApplyResult, ...]) -> dict[Path, tuple[ApplyStatus, str]]:
    return {r.source: (r.status, r.reason) for r in results}


@pytest.fixture
def show(tmp_path: Path) -> Iterator[Path]:
    show = _two_discs(tmp_path)
    _write(show / "Disc 1" / "Show.Name.S01E01.srt", b"subs")
    yield show


def _plan(show: Path) -> Plan:
    return plan_queue([show], _options(), _provider()).plan


def test_a_file_entry_is_not_moved_onto_a_file_that_appears(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    [dest] = [e.destination for e in plan.entries if e.source == video]
    assert dest is not None
    _appears_after_the_check(monkeypatch, dest, _a_file)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[video] == TAKEN
    assert video.read_bytes() == b"x"
    assert dest.read_bytes() == b"appeared"
    assert all(m.source != video for m in outcome.moves)


def test_a_sidecar_is_not_moved_onto_a_file_that_appears(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    sidecar = show / "Disc 1" / "Show.Name.S01E01.srt"
    [dest] = [e.destination for e in plan.entries if e.source == sidecar]
    assert dest is not None
    _appears_after_the_check(monkeypatch, dest, _a_file)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[sidecar] == TAKEN
    assert sidecar.read_bytes() == b"subs"
    assert dest.read_bytes() == b"appeared"


def test_a_file_straggler_is_not_moved_onto_a_file_that_appears(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    notes = show / "Disc 1" / "notes.txt"
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    _appears_after_the_check(monkeypatch, dest, _a_file)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[notes] == TAKEN
    assert notes.read_bytes() == b"x"
    assert dest.read_bytes() == b"appeared"


@pytest.mark.parametrize("make", [_a_file, _a_folder], ids=["file", "empty folder"])
def test_a_folder_straggler_is_not_moved_onto_anything_that_appears(
    show: Path, monkeypatch: pytest.MonkeyPatch, make: Callable[[Path], None]
) -> None:
    plan = _plan(show)
    subs = show / "Disc 1" / "Subs"
    [dest] = [s.destination for s in plan.stragglers if s.source == subs]
    _appears_after_the_check(monkeypatch, dest, make)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[subs] == TAKEN
    assert (subs / "English.srt").read_bytes() == b"x"
    assert dest.exists(follow_symlinks=False)
    assert not (dest / "English.srt").exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows renames, it never hard-links")
def test_where_no_hard_link_can_be_made_the_move_still_refuses_a_taken_name(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", no_link)
    plan = _plan(show)
    notes = show / "Disc 1" / "notes.txt"
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    _appears_after_the_check(monkeypatch, dest, _a_file)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[notes] == TAKEN
    assert dest.read_bytes() == b"appeared"
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    assert _by_source(outcome.results)[video] == (ApplyStatus.RENAMED, "ok")
    assert not video.exists()


def test_a_move_whose_new_place_cannot_be_read_is_still_recorded(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    notes = show / "Disc 1" / "notes.txt"
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    size = notes.stat().st_size
    real_lstat = os.lstat

    def lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if isinstance(path, (str, os.PathLike)) and os.fspath(path) == str(dest):
            raise PermissionError(errno.EACCES, "Permission denied", str(dest))
        return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", lstat)
        outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[notes] == (ApplyStatus.RENAMED, "ok")
    [move] = [m for m in outcome.moves if m.source == notes]
    assert move.destination == dest
    assert move.fingerprint is not None
    assert (move.fingerprint.path, move.fingerprint.size) == (dest, size)
    assert dest.read_bytes() == b"x"
