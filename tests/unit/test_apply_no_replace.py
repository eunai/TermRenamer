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
from termrenamer.core.models import ApplyResult, ApplyStatus, Candidate, Plan
from termrenamer.core.moving import Changes, move_no_replace
from termrenamer.core.planning import plan_queue

from .links import needs_symlinks, point_folder_at
from .test_plan_queue import TvStandIn
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
    # Nothing was written through the link: its target is still missing.
    missing = path.parent / "missing target"
    return path.is_symlink() and os.readlink(path) == "missing target" and not missing.exists()


def _claims(
    monkeypatch: pytest.MonkeyPatch,
    at: Path,
    make: Callable[[Path], None],
    *,
    no_hard_link: int | None = None,
) -> None:
    """Make something appear at ``at`` just before the call that claims that name; with
    ``no_hard_link``, a hard link (on Windows a rename from another folder, as across
    drives) fails with that error, so the move takes the copy path."""
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
        if WINDOWS and no_hard_link is not None and _between_folders(src, dst):
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


def _between_folders(src: object, dst: object) -> bool:
    return Path(os.fspath(src)).parent != Path(os.fspath(dst)).parent  # type: ignore[call-overload]


def _across_drives(monkeypatch: pytest.MonkeyPatch, only: Path | None = None) -> None:
    """Every move (with ``only``, the move of that source) takes the copy path: a hard
    link, and a rename from one folder to another, fail as they do to another drive. A
    rename within a folder works, as the one that claims a Windows copy's new name."""
    real_link, real_rename = os.link, os.rename

    def moved(src: object) -> bool:
        return only is None or os.fspath(src) == str(only)  # type: ignore[call-overload]

    def no_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if moved(src):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    def rename(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if moved(src) and _between_folders(src, dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_rename(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "rename", rename)


def _in_folder_of(path: object, dest: Path) -> bool:
    """Whether ``path`` is in ``dest``'s folder: ``dest`` itself, or the fresh name a
    Windows copy is made under before it is renamed to ``dest``."""
    return Path(os.fspath(path)).parent == dest.parent  # type: ignore[call-overload]


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
    if WINDOWS and path_name == "copy ENOTSUP":
        # A hard link that fails on a filesystem without them. A Windows move makes no
        # hard link: only a rename that fails across drives copies, the copy EXDEV case.
        pytest.skip(
            "a Windows move makes no hard link, so a filesystem without them takes no "
            "copy path there; the copy path across drives runs as copy EXDEV"
        )
    if kind == "broken link":
        needs_symlinks(show)
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
    assert outcome.files_left_behind == ()
    # No copy is left under another name.
    assert not [name for name in os.listdir(dest.parent) if name.startswith(".termrenamer-")]


@pytest.mark.parametrize("path_name", ["link", "copy EXDEV"])
@pytest.mark.parametrize("kind", list(KINDS))
def test_nothing_at_the_new_name_of_a_symbolic_link_straggler_is_replaced(
    show: Path, monkeypatch: pytest.MonkeyPatch, kind: str, path_name: str
) -> None:
    needs_symlinks(show)
    link = show / "Disc 1" / "notes link.txt"
    link.symlink_to("notes.txt")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == link]
    make = KINDS[kind]
    _claims(monkeypatch, dest, make, no_hard_link=PATHS[path_name])

    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.stragglers)[link] == TAKEN
    assert _is_untouched(dest, make)
    assert os.readlink(link) == "notes.txt"
    assert outcome.files_left_behind == ()
    assert not [name for name in os.listdir(dest.parent) if name.startswith(".termrenamer-")]


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


def test_a_copy_whose_source_changes_during_it_fails_and_leaves_the_source(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        if os.fstat(fd).st_size == len(b"my notes"):  # the notes' copy
            notes.write_bytes(b"my notes, and more")
        real_fsync(fd)

    _across_drives(monkeypatch, only=notes)
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


def test_a_failed_copy_that_cannot_be_removed_is_listed_as_left_behind(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_unlink, real_fsync = os.unlink, os.fsync

    def fsync(fd: int) -> None:
        if os.fstat(fd).st_size == len(b"my notes"):  # the notes' copy
            raise OSError(errno.EIO, "Input/output error")
        real_fsync(fd)

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        if _in_folder_of(path, dest):
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))  # type: ignore[call-overload]
        real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    _across_drives(monkeypatch, only=notes)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "unlink", unlink)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.stragglers)[notes][0] is ApplyStatus.FAIL
    assert notes.read_bytes() == b"my notes"
    [left] = outcome.files_left_behind
    assert left.parent == dest.parent and left.exists()


def test_a_move_whose_new_place_cannot_be_read_is_still_recorded(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.core import moving

    plan = _plan(show)
    notes = show / "Disc 1" / "notes.txt"
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    size = notes.stat().st_size
    real = moving._fingerprint

    def fingerprint(path: Path, st: os.stat_result | None = None) -> object:
        if path == dest and st is None:
            raise PermissionError(errno.EACCES, "Permission denied", str(dest))
        return real(path, st)

    monkeypatch.setattr(moving, "_fingerprint", fingerprint)
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


def test_a_hard_link_in_the_same_folder_under_another_exact_name_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "show name.mkv", b"v")
    dest = tmp_path / "Show Name.mkv"
    real_listdir = os.listdir
    if not _ignores_letter_case(tmp_path):
        os.link(source, dest)  # this filesystem holds both exact names

    def listdir(path: object = ".") -> list[str]:
        names = real_listdir(path)  # type: ignore[arg-type]
        if os.fspath(path) == str(tmp_path):  # type: ignore[call-overload]
            # Two exact names in one folder: a separate hard link, as a case-sensitive
            # filesystem can hold it.
            return sorted({*names, source.name, dest.name})
        return names

    monkeypatch.setattr(os, "listdir", listdir)
    changes = Changes()
    with pytest.raises(FileExistsError):
        move_no_replace(source, dest, changes)
    monkeypatch.undo()

    assert source.read_bytes() == b"v"
    assert changes.moves == []


def test_a_case_only_rename_whose_new_name_cannot_be_confirmed_fails_and_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _ignores_letter_case(tmp_path):
        pytest.skip("on this filesystem a new letter case is a new name, not a case-only rename")
    source = _write(tmp_path / "show name.mkv", b"v")
    dest = tmp_path / "Show Name.mkv"
    real_listdir, real_rename = os.listdir, os.rename
    renamed: list[bool] = []

    def rename(src: object, dst: object) -> None:
        real_rename(src, dst)  # type: ignore[arg-type]
        renamed.append(True)

    def listdir(path: object = ".") -> list[str]:
        if renamed:
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))  # type: ignore[call-overload]
        return real_listdir(path)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "listdir", listdir)
    changes = Changes()
    with pytest.raises(OSError, match="could not be confirmed"):
        move_no_replace(source, dest, changes)
    monkeypatch.undo()

    assert [(m.source, m.destination) for m in changes.moves] == [(source, dest)]


def test_a_copy_whose_source_changes_just_before_its_removal_keeps_the_source(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_open, real_close = os.open, os.close
    copies: list[int] = []

    def open_(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if flags & os.O_EXCL and _in_folder_of(path, dest):
            copies.append(fd)
        return fd

    def close(fd: int) -> None:
        real_close(fd)
        if fd in copies:  # the copy is done and checked; the source changes now
            copies.remove(fd)
            notes.write_bytes(b"my notes, newer")

    _across_drives(monkeypatch, only=notes)
    monkeypatch.setattr(os, "open", open_)
    monkeypatch.setattr(os, "close", close)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    status, reason = _by_source(outcome.stragglers)[notes]
    assert status is ApplyStatus.FAIL
    assert "the source changed during its move" in reason
    assert notes.read_bytes() == b"my notes, newer"
    assert not dest.exists(follow_symlinks=False)
    assert outcome.files_left_behind == ()


def test_a_new_name_made_by_exclusive_create_is_listed_until_its_copy_is_removed(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = _write(show / "Disc 1" / "notes.txt", b"my notes")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real_open, real_fstat, real_close = os.open, os.fstat, os.close
    made: list[int] = []
    raised: list[int] = []
    closed: list[int] = []

    def open_(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if flags & os.O_EXCL and _in_folder_of(path, dest):
            made.append(fd)
        return fd

    def fstat(fd: int) -> os.stat_result:
        if made and fd == made[0] and not raised:
            raised.append(fd)
            raise OSError(errno.EIO, "Input/output error")
        return real_fstat(fd)

    def close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    _across_drives(monkeypatch, only=notes)
    monkeypatch.setattr(os, "open", open_)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "close", close)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.stragglers)[notes][0] is ApplyStatus.FAIL
    assert notes.read_bytes() == b"my notes"
    [left] = outcome.files_left_behind
    assert left.parent == dest.parent and left.exists()
    assert made and made[0] in closed


def test_a_move_is_kept_whatever_reading_its_new_place_raises(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.core import moving

    plan = _plan(show)
    notes = show / "Disc 1" / "notes.txt"
    [dest] = [s.destination for s in plan.stragglers if s.source == notes]
    real = moving._fingerprint

    def fingerprint(path: Path, st: os.stat_result | None = None) -> object:
        if path == dest and st is None:
            raise RuntimeError("unexpected")
        return real(path, st)

    monkeypatch.setattr(moving, "_fingerprint", fingerprint)
    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[notes] == (ApplyStatus.RENAMED, "ok")
    assert (notes, dest) in [(m.source, m.destination) for m in outcome.moves]


def test_a_link_to_a_folder_is_moved_as_itself_and_never_entered(
    show: Path, tmp_path: Path
) -> None:
    needs_symlinks(tmp_path)
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "bonus.txt", b"bonus")
    (show / "Disc 1" / "Extras").symlink_to(elsewhere, target_is_directory=True)
    (show / "Disc 1" / "Subs" / "Linked").symlink_to(elsewhere, target_is_directory=True)
    plan = _plan(show)

    disc_1 = next(f for f in plan.source_folders if f.path == show / "Disc 1")
    assert show / "Disc 1" / "Extras" in disc_1.files
    outcome = apply_plan(plan, confirmed=True)

    season = show / "Show Name" / "Season 01"
    for moved in (season / "Extras", season / "Subs" / "Linked"):
        assert moved.is_symlink()
        assert os.path.samestat(os.stat(moved), os.stat(elsewhere))
    assert _by_source(outcome.stragglers)[show / "Disc 1" / "Extras"] == (ApplyStatus.RENAMED, "ok")
    assert (elsewhere / "bonus.txt").read_bytes() == b"bonus"
    assert all(elsewhere not in m.source.parents for m in outcome.moves)


def test_a_junction_is_never_entered(
    show: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No real junction outside Windows: a folder stands in, and isjunction says so.
    extras = show / "Disc 1" / "Extras"
    inner = show / "Disc 1" / "Subs" / "Junction"
    _write(extras / "behind.txt", b"behind")
    _write(inner / "behind.txt", b"behind")
    real = os.path.isjunction
    monkeypatch.setattr(os.path, "isjunction", lambda p: p in (extras, inner) or real(p))
    plan = _plan(show)

    disc_1 = next(f for f in plan.source_folders if f.path == show / "Disc 1")
    assert extras in disc_1.files
    outcome = apply_plan(plan, confirmed=True)

    # Moved as itself where the system can (Windows renames it), else it fails and stays.
    for junction in (extras, inner):
        assert all(junction not in m.source.parents for m in outcome.moves)
    if WINDOWS:
        assert _by_source(outcome.stragglers)[extras] == (ApplyStatus.RENAMED, "ok")
    else:
        status, reason = _by_source(outcome.stragglers)[extras]
        assert status is ApplyStatus.FAIL
        assert "junction" in reason
        assert (extras / "behind.txt").read_bytes() == b"behind"
        assert (inner / "behind.txt").read_bytes() == b"behind"


@pytest.mark.skipif(not WINDOWS, reason="a junction exists only on Windows")
def test_a_real_junction_is_moved_as_itself_and_never_entered(show: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "bonus.txt", b"bonus")
    extras = show / "Disc 1" / "Extras"
    point_folder_at(extras, elsewhere)
    plan = _plan(show)

    disc_1 = next(f for f in plan.source_folders if f.path == show / "Disc 1")
    assert extras in disc_1.files
    outcome = apply_plan(plan, confirmed=True)

    moved = show / "Show Name" / "Season 01" / "Extras"
    assert os.path.isjunction(moved)
    assert os.path.samestat(os.stat(moved), os.stat(elsewhere))
    assert _by_source(outcome.stragglers)[extras] == (ApplyStatus.RENAMED, "ok")
    assert (elsewhere / "bonus.txt").read_bytes() == b"bonus"
    assert all(elsewhere not in m.source.parents for m in outcome.moves)


def test_apply_returns_its_outcome_with_the_working_folder_inside_a_folder_straggler(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(show)
    subs = show / "Disc 1" / "Subs"
    monkeypatch.chdir(subs)  # changed back after the test

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[subs] == (ApplyStatus.RENAMED, "ok")
    assert subs in outcome.folders_removed
    assert (show / "Show Name" / "Season 01" / "Subs" / "English.srt").read_bytes() == b"x"


def _ignores_letter_case(folder: Path) -> bool:
    probe = _write(folder / "case probe", b"")
    try:
        return (folder / "CASE PROBE").exists()
    finally:
        probe.unlink()


def test_two_source_folders_whose_names_differ_only_in_letter_case_keep_their_stragglers(
    tmp_path: Path,
) -> None:
    if _ignores_letter_case(tmp_path):
        pytest.skip("this filesystem cannot hold Disc and disc side by side")
    backups = tmp_path / "Backups"
    _write(backups / "Disc" / "Alpha.S01E01.mkv")
    _write(backups / "Disc" / "alpha.jpg", b"a")
    _write(backups / "disc" / "Beta.S01E01.mkv")
    _write(backups / "disc" / "beta.jpg", b"b")
    backups = backups.resolve()
    provider = TvStandIn(
        shows={
            "alpha": (Candidate(id="1", name="Alpha", year=2010),),
            "beta": (Candidate(id="2", name="Beta", year=2011),),
        },
        episodes={("1", 1, 1): "Pilot", ("2", 1, 1): "Pilot"},
    )
    plan = plan_queue([backups], _options(), provider).plan
    # Alpha's video changes, so nothing moves out of Disc; Beta's does move out of disc.
    (backups / "Disc" / "Alpha.S01E01.mkv").write_bytes(b"changed")

    outcome = apply_plan(plan, confirmed=True)

    by_source = _by_source(outcome.stragglers)
    assert by_source[backups / "Disc" / "alpha.jpg"] == (
        ApplyStatus.SKIP,
        "nothing moved out of its folder",
    )
    assert by_source[backups / "disc" / "beta.jpg"] == (ApplyStatus.RENAMED, "ok")
    assert (backups / "Beta" / "Season 01" / "beta.jpg").read_bytes() == b"b"
    assert (backups / "Disc" / "alpha.jpg").read_bytes() == b"a"


@pytest.mark.skipif(WINDOWS, reason="no named pipes in the filesystem on Windows")
def test_a_pipe_is_never_copied_and_apply_returns(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.mkfifo(show / "Disc 1" / "Subs" / "pipe")
    plan = _plan(show)
    subs = show / "Disc 1" / "Subs"

    _across_drives(monkeypatch)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    status, reason = _by_source(outcome.stragglers)[subs]
    assert status is ApplyStatus.FAIL
    assert "only a file or a symbolic link can be copied" in reason
    assert (subs / "pipe").exists()


def test_the_working_folder_is_left_when_the_plan_spells_its_folder_in_another_case(
    show: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    typed = show.parent / show.name.lower()
    if not typed.exists():
        pytest.skip("this filesystem tells letter case apart")
    plan = plan_queue([typed], _options(), _provider()).plan
    monkeypatch.chdir(show / "Disc 1" / "Subs")  # changed back after the test

    outcome = apply_plan(plan, confirmed=True)

    assert os.path.samestat(os.stat(os.getcwd()), os.stat(show))
    assert typed / "Disc 1" / "Subs" in outcome.folders_removed
