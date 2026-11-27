"""Apply never replaces anything: every new name is claimed by the call that makes it, so
something that appears at the name just before that call is left as it is; and the
outcome lists every change Apply made, whatever fails."""

from __future__ import annotations

import errno
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from termrenamer.core import apply as apply_module
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyResult, ApplyStatus, Plan
from termrenamer.core.moving import Changes, move_no_replace
from termrenamer.core.planning import plan_queue

from .test_plan_stragglers import _options, _provider, _two_discs, _write

TAKEN = (ApplyStatus.SKIP, "destination exists at apply time")
WINDOWS = os.name == "nt"


def _a_file(path: Path) -> None:
    path.write_bytes(b"appeared")


def _a_folder(path: Path) -> None:
    path.mkdir()


def _a_broken_link(path: Path) -> None:
    path.symlink_to("missing target")


def _is_untouched(path: Path, make: Callable[[Path], None]) -> bool:
    if make is _a_file:
        return path.read_bytes() == b"appeared"
    if make is _a_folder:
        return path.is_dir() and not any(path.iterdir())
    return path.is_symlink() and os.readlink(path) == "missing target"


def _claims(
    monkeypatch: pytest.MonkeyPatch,
    at: Path,
    make: Callable[[Path], None],
    *,
    no_hard_link: int | None = None,
) -> None:
    """Make something appear at ``at`` just before the call that claims that name; with
    ``no_hard_link``, a hard link (on Windows a rename) fails with that error, so the
    move takes the copy path."""
    planted: list[Path] = []
    real_link, real_open, real_mkdir = os.link, os.open, os.mkdir
    real_rename, real_symlink = os.rename, os.symlink

    def plant(target: object) -> None:
        if not planted and os.fspath(target) == str(at):  # type: ignore[call-overload]
            planted.append(at)
            make(at)

    def link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if no_hard_link is not None:
            raise OSError(no_hard_link, os.strerror(no_hard_link))
        plant(dst)
        real_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    def open_(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if flags & os.O_EXCL:
            plant(path)
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    def mkdir(path: object, *args: object, **kwargs: object) -> None:
        plant(path)
        real_mkdir(path, *args, **kwargs)  # type: ignore[arg-type]

    def rename(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if WINDOWS and no_hard_link is not None:
            raise OSError(no_hard_link, os.strerror(no_hard_link))
        plant(dst)
        real_rename(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    def symlink(src: object, dst: object, *args: object, **kwargs: object) -> None:
        plant(dst)
        real_symlink(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    for name, fake in (
        ("link", link),
        ("open", open_),
        ("mkdir", mkdir),
        ("rename", rename),
        ("symlink", symlink),
    ):
        monkeypatch.setattr(os, name, fake)


def _by_source(results: tuple[ApplyResult, ...]) -> dict[Path, tuple[ApplyStatus, str]]:
    return {r.source: (r.status, r.reason) for r in results}


@pytest.fixture
def show(tmp_path: Path) -> Iterator[Path]:
    show = _two_discs(tmp_path)
    _write(show / "Disc 1" / "Show.Name.S01E01.srt", b"subs")
    yield show


def _plan(show: Path) -> Plan:
    return plan_queue([show], _options(), _provider()).plan


def _video(show: Path) -> Path:
    return show / "Disc 1" / "Show.Name.S01E01.mkv"


# Each item: where its source is, how to find its planned name, and what it holds.
ITEMS = {
    "video": ("Disc 1/Show.Name.S01E01.mkv", "entry", b"x"),
    "Sidecar": ("Disc 1/Show.Name.S01E01.srt", "entry", b"subs"),
    "file Straggler": ("Disc 1/notes.txt", "straggler", b"x"),
    "folder Straggler": ("Disc 1/Subs", "straggler", None),
}
KINDS = {"file": _a_file, "empty folder": _a_folder, "broken link": _a_broken_link}
PATHS = {"link": None, "copy EXDEV": errno.EXDEV, "copy ENOTSUP": errno.ENOTSUP}


@pytest.mark.parametrize("path_name", list(PATHS))
@pytest.mark.parametrize("kind", list(KINDS))
@pytest.mark.parametrize("item", list(ITEMS))
def test_nothing_that_appears_at_a_new_name_just_before_it_is_claimed_is_replaced(
    show: Path, monkeypatch: pytest.MonkeyPatch, item: str, kind: str, path_name: str
) -> None:
    if WINDOWS and (kind == "broken link" or path_name == "copy ENOTSUP"):
        pytest.skip("no symbolic links without privilege; Windows copies only across drives")
    relative, listed_as, data = ITEMS[item]
    source = show.joinpath(*relative.split("/"))
    plan = _plan(show)
    listed = plan.entries if listed_as == "entry" else plan.stragglers
    [dest] = [x.destination for x in listed if x.source == source]
    assert dest is not None
    make = KINDS[kind]
    _claims(monkeypatch, dest, make, no_hard_link=PATHS[path_name])

    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    results = outcome.results if listed_as == "entry" else outcome.stragglers
    assert _by_source(results)[source] == TAKEN
    assert _is_untouched(dest, make)
    if data is None:
        assert (source / "English.srt").read_bytes() == b"x"
    else:
        assert source.read_bytes() == data
    assert all(m.source != source and m.source.parent != source for m in outcome.moves)
    assert dest not in outcome.folders_created


def test_a_separate_hard_link_of_the_source_at_its_new_name_is_taken(show: Path) -> None:
    plan = _plan(show)
    video = _video(show)
    [dest] = [e.destination for e in plan.entries if e.source == video]
    assert dest is not None
    dest.parent.mkdir(parents=True)
    os.link(video, dest)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[video] == TAKEN
    assert os.path.samestat(os.lstat(video), os.lstat(dest))
    assert all(m.source != video for m in outcome.moves)


def test_a_plan_built_with_a_hard_link_at_the_new_name_numbers_it(show: Path) -> None:
    first = _plan(show)
    video = _video(show)
    [dest] = [e.destination for e in first.entries if e.source == video]
    assert dest is not None
    dest.parent.mkdir(parents=True)
    os.link(video, dest)

    plan = _plan(show)

    [renumbered] = [e.destination for e in plan.entries if e.source == video]
    assert renumbered == dest.with_name(f"{dest.stem} (1){dest.suffix}")


def test_a_case_only_rename_is_made(tmp_path: Path) -> None:
    source = _write(tmp_path / "show name.mkv", b"v")
    dest = tmp_path / "Show Name.mkv"
    changes = Changes()

    move_no_replace(source, dest, changes)

    assert os.listdir(tmp_path) == ["Show Name.mkv"]
    assert [(m.source, m.destination) for m in changes.moves] == [(source, dest)]


@pytest.mark.skipif(WINDOWS, reason="Windows copies only across drives")
def test_a_copy_whose_source_changes_during_it_fails_and_leaves_the_source(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_fsync = os.fsync

    def no_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def fsync(fd: int) -> None:
        if os.fstat(fd).st_size == len(b"my notes"):  # the notes' copy
            notes.write_bytes(b"my notes, and more")
        real_fsync(fd)

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "fsync", fsync)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    status, reason = _by_source(outcome.stragglers)[notes]
    assert status is ApplyStatus.FAIL
    assert "changed during the copy" in reason
    assert notes.read_bytes() == b"my notes, and more"
    assert not dest.exists(follow_symlinks=False)
    assert all(m.source != notes for m in outcome.moves)
    assert outcome.files_left_behind == ()


@pytest.mark.skipif(WINDOWS, reason="Windows copies only across drives")
def test_a_failed_copy_that_cannot_be_removed_is_listed_as_left_behind(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_unlink, real_fsync = os.unlink, os.fsync

    def no_link(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def fsync(fd: int) -> None:
        if os.fstat(fd).st_size == len(b"my notes"):  # the notes' copy
            raise OSError(errno.EIO, "Input/output error")
        real_fsync(fd)

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        if os.fspath(path) == str(dest):  # type: ignore[call-overload]
            raise PermissionError(errno.EACCES, "Permission denied", str(dest))
        real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "unlink", unlink)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.stragglers)[notes][0] is ApplyStatus.FAIL
    assert notes.read_bytes() == b"my notes"
    assert outcome.files_left_behind == (dest,)


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
    assert (move.destination, move.fingerprint.path, move.fingerprint.size) == (dest, dest, size)
    assert dest.read_bytes() == b"x"


def test_a_source_that_cannot_be_read_fails_alone_and_apply_goes_on(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    video = _video(show)
    real = apply_module.fingerprint

    def fingerprint(path: Path) -> object:
        if path == video:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real(path)

    monkeypatch.setattr(apply_module, "fingerprint", fingerprint)
    outcome = apply_plan(plan, confirmed=True)

    status, reason = _by_source(outcome.results)[video]
    assert (status, reason.startswith("cannot read the source: ")) == (ApplyStatus.FAIL, True)
    second = show / "Disc 2" / "Show.Name.S01E02.mkv"
    assert _by_source(outcome.results)[second] == (ApplyStatus.RENAMED, "ok")
    assert [m.source for m in outcome.moves][0] == second


def test_a_source_that_disappears_as_it_is_checked_is_stale(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    video = _video(show)
    real = apply_module.fingerprint

    def fingerprint(path: Path) -> object:
        if path == video:
            path.unlink()
        return real(path)

    monkeypatch.setattr(apply_module, "fingerprint", fingerprint)
    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[video] == (ApplyStatus.SKIP, "stale: source missing")


def test_a_folder_straggler_whose_child_fails_keeps_what_moved_and_the_rest(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subs = show / "Disc 1" / "Subs"
    _write(subs / "French.srt", b"fr")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == subs]
    real_link, real_rename = os.link, os.rename

    def refuse_french(real: Callable[..., None]) -> Callable[..., None]:
        def call(src: object, dst: object, *args: object, **kwargs: object) -> None:
            if os.fspath(src).endswith("French.srt"):  # type: ignore[call-overload]
                raise PermissionError(errno.EACCES, "Permission denied", os.fspath(src))  # type: ignore[call-overload]
            real(src, dst, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "link", refuse_french(real_link))
    monkeypatch.setattr(os, "rename", refuse_french(real_rename))
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    status, reason = _by_source(outcome.stragglers)[subs]
    assert status is ApplyStatus.FAIL
    assert "French.srt" in reason
    assert (dest / "English.srt").read_bytes() == b"x"
    assert (subs / "French.srt").read_bytes() == b"fr"
    assert (subs / "English.srt", dest / "English.srt") in [
        (m.source, m.destination) for m in outcome.moves
    ]
    assert dest in outcome.folders_created
    assert subs not in outcome.folders_removed


def test_an_unexpected_error_stops_apply_and_the_outcome_so_far_is_returned(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    second = show / "Disc 2" / "Show.Name.S01E02.mkv"
    real = apply_module.move_no_replace

    def move(source: Path, dest: Path, changes: Changes) -> None:
        if source == second:
            raise RuntimeError("boom")
        real(source, dest, changes)

    monkeypatch.setattr(apply_module, "move_no_replace", move)
    outcome = apply_plan(plan, confirmed=True)

    by_source = _by_source(outcome.results)
    assert by_source[_video(show)] == (ApplyStatus.RENAMED, "ok")
    assert by_source[second] == (ApplyStatus.FAIL, "unexpected error: RuntimeError('boom')")
    stopped = (ApplyStatus.SKIP, "not applied: Apply stopped after an unexpected error")
    assert by_source[show / "Disc 1" / "Show.Name.S01E01.srt"] == stopped
    assert set(_by_source(outcome.stragglers).values()) == {stopped}
    assert [m.source for m in outcome.moves] == [_video(show)]
    assert outcome.folders_removed == ()
    assert (show / "Disc 1" / "notes.txt").exists()
