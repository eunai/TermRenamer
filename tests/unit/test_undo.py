"""Undo puts back what the last Apply moved, from its outcome alone, last move first, and
never replaces anything (spec #16, section H)."""

from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path

import pytest

from termrenamer.core import apply as apply_module
from termrenamer.core import undo as undo_module
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyOutcome,
    ApplyResult,
    ApplyStatus,
    Move,
    Plan,
    PlanFingerprint,
)
from termrenamer.core.moving import Changes, move_no_replace
from termrenamer.core.planning import plan_queue
from termrenamer.core.undo import undo_apply

from .test_apply_no_replace import _ignores_letter_case
from .test_plan_stragglers import _options, _provider, _two_discs, _write

WINDOWS = os.name == "nt"

Listing = dict[str, tuple[str, int, int] | tuple[str]]


def listing(root: Path) -> Listing:
    """Every file and folder under ``root`` by its path from ``root``: a file with its size
    and modification time, a folder by its name only (adding and removing names changes
    a folder's own time)."""
    found: Listing = {}
    for path in root.rglob("*"):
        st = os.lstat(path)
        name = path.relative_to(root).as_posix()
        if stat.S_ISDIR(st.st_mode):
            found[name] = ("folder",)
        else:
            found[name] = ("file", st.st_size, st.st_mtime_ns)
    return found


def _show(tmp_path: Path) -> Path:
    """Two discs of one show, a Sidecar, file Stragglers and a folder Straggler."""
    show = _two_discs(tmp_path)
    _write(show / "Disc 1" / "Show.Name.S01E01.srt", b"subs")
    return show


def _plan(show: Path) -> Plan:
    return plan_queue([show], _options(), _provider()).plan


def test_a_full_undo_puts_the_tree_back_as_it_was_before_apply(tmp_path: Path) -> None:
    show = _show(tmp_path)
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)
    assert listing(show) != before

    undone = undo_apply(applied)

    assert listing(show) == before
    assert [r.status for r in undone.results] == [ApplyStatus.RENAMED] * len(applied.moves)
    assert undone.put_back == len(applied.moves)
    assert undone.left == 0


def _season(show: Path) -> Path:
    return show / "Show Name" / "Season 01"


def _by_source(undone_results: tuple[ApplyResult, ...]) -> dict[Path, tuple[ApplyStatus, str]]:
    return {r.source: (r.status, r.reason) for r in undone_results}


def _outcome_of(changes: Changes) -> ApplyOutcome:
    """An outcome holding only the changes made directly through ``changes``."""
    return ApplyOutcome(
        results=(),
        stragglers=(),
        moves=tuple(changes.moves),
        folders_created=tuple(changes.folders_created),
        folders_removed=tuple(changes.folders_removed),
        files_left_behind=tuple(changes.files_left_behind),
    )


def _link_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"this system makes no symbolic link without privilege: {exc}")


def test_undo_puts_the_moves_back_last_move_first(tmp_path: Path) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)

    undone = undo_apply(applied)

    assert [(r.source, r.destination) for r in undone.results] == [
        (m.destination, m.source) for m in reversed(applied.moves)
    ]


def test_the_removed_folders_are_made_again_and_the_folders_apply_made_removed(
    tmp_path: Path,
) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    season = _season(show)
    assert applied.folders_removed == (show / "Disc 1" / "Subs", show / "Disc 1", show / "Disc 2")

    undone = undo_apply(applied)

    # Each made before the folders inside it; each removed before its parent.
    assert undone.folders_made_again == (
        show / "Disc 2",
        show / "Disc 1",
        show / "Disc 1" / "Subs",
    )
    assert undone.folders_removed == (season / "Subs", season, show / "Show Name")
    assert not (show / "Show Name").exists()


def test_a_folder_straggler_goes_back_as_its_files_into_its_folders_made_again(
    tmp_path: Path,
) -> None:
    show = _show(tmp_path)
    _write(show / "Disc 1" / "Subs" / "French.srt", b"fr")
    (show / "Disc 1" / "Subs" / "Empty").mkdir()
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)
    moved_subs = _season(show) / "Subs"
    assert sorted(os.listdir(moved_subs)) == ["Empty", "English.srt", "French.srt"]

    undone = undo_apply(applied)

    assert listing(show) == before
    assert _by_source(undone.results)[moved_subs / "French.srt"] == (ApplyStatus.RENAMED, "ok")
    assert show / "Disc 1" / "Subs" / "Empty" in undone.folders_made_again
    assert moved_subs / "Empty" in undone.folders_removed


def test_a_file_changed_since_apply_is_left_with_the_folders_it_needs(tmp_path: Path) -> None:
    show = _show(tmp_path)
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)
    changed = _season(show) / "Show Name - S01E02 - Second.mkv"
    changed.write_bytes(b"changed after Apply")

    undone = undo_apply(applied)

    assert _by_source(undone.results)[changed] == (
        ApplyStatus.SKIP,
        "changed since Apply: its size or modification time changed",
    )
    assert (undone.put_back, undone.left) == (len(applied.moves) - 1, 1)
    assert changed.read_bytes() == b"changed after Apply"
    expected = dict(before)
    del expected["Disc 2/Show.Name.S01E02.mkv"]
    expected["Show Name"] = ("folder",)
    expected["Show Name/Season 01"] = ("folder",)
    found = listing(show)
    del found["Show Name/Season 01/Show Name - S01E02 - Second.mkv"]
    assert found == expected


def test_a_file_whose_time_alone_changed_is_left(tmp_path: Path) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    touched = _season(show) / "notes.txt"
    st = os.lstat(touched)
    os.utime(touched, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    undone = undo_apply(applied)

    assert _by_source(undone.results)[touched][0] is ApplyStatus.SKIP
    assert touched.exists()
    assert not (show / "Disc 1" / "notes.txt").exists()


def test_a_file_whose_old_place_is_taken_is_left_and_nothing_there_is_replaced(
    tmp_path: Path,
) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    _write(show / "Disc 1" / "notes.txt", b"new notes")

    undone = undo_apply(applied)

    moved = _season(show) / "notes.txt"
    assert _by_source(undone.results)[moved] == (ApplyStatus.SKIP, "its old place is taken")
    assert (show / "Disc 1" / "notes.txt").read_bytes() == b"new notes"
    assert moved.read_bytes() == b"x"
    assert (show / "Disc 1" / "Show.Name.S01E01.mkv").exists()


@pytest.mark.parametrize("kind", ["empty folder", "broken link"])
def test_an_old_place_taken_by_a_folder_or_a_broken_link_is_left(tmp_path: Path, kind: str) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    taken = show / "Disc 2" / "folder.jpg"
    taken.parent.mkdir()
    if kind == "empty folder":
        taken.mkdir()
    else:
        _link_or_skip(taken, tmp_path / "missing target")

    undone = undo_apply(applied)

    moved = _season(show) / "folder (1).jpg"
    assert _by_source(undone.results)[moved] == (ApplyStatus.SKIP, "its old place is taken")
    assert moved.exists()
    assert taken.is_dir() if kind == "empty folder" else taken.is_symlink()


def test_a_file_gone_from_its_new_place_is_left(tmp_path: Path) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    gone = _season(show) / "folder.jpg"
    gone.unlink()

    undone = undo_apply(applied)

    assert _by_source(undone.results)[gone] == (ApplyStatus.SKIP, "no longer at its new place")
    assert not (show / "Disc 1" / "folder.jpg").exists()


def test_a_case_only_rename_is_undone(tmp_path: Path) -> None:
    source = _write(tmp_path / "show name.mkv", b"v")
    changes = Changes()
    move_no_replace(source, tmp_path / "Show Name.mkv", changes)

    undone = undo_apply(_outcome_of(changes))

    assert os.listdir(tmp_path) == ["show name.mkv"]
    assert (undone.put_back, undone.left) == (1, 0)


def test_an_unconfirmed_case_only_rename_goes_back_by_what_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _ignores_letter_case(tmp_path):
        pytest.skip("on this filesystem a new letter case is a new name, not a case-only rename")
    source = _write(tmp_path / "show name.mkv", b"v")
    real_listdir = os.listdir
    renamed: list[bool] = []
    real_rename = os.rename

    def rename(src: object, dst: object) -> None:
        real_rename(src, dst)  # type: ignore[arg-type]
        renamed.append(True)

    def listdir(path: object = ".") -> list[str]:
        if renamed and len(renamed) == 1:
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))  # type: ignore[call-overload]
        return real_listdir(path)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "listdir", listdir)
    changes = Changes()
    with pytest.raises(OSError, match="could not be confirmed"):
        move_no_replace(source, tmp_path / "Show Name.mkv", changes)
    renamed.append(True)  # the listing works again for Undo
    monkeypatch.undo()

    undone = undo_apply(_outcome_of(changes))

    assert os.listdir(tmp_path) == ["show name.mkv"]
    assert undone.results[0].status is ApplyStatus.RENAMED


def test_a_case_only_rename_the_disk_never_made_is_found_at_its_old_place(
    tmp_path: Path,
) -> None:
    if not _ignores_letter_case(tmp_path):
        pytest.skip("on this filesystem a new letter case is a new name, not a case-only rename")
    old = _write(tmp_path / "show name.mkv", b"v")
    st = os.lstat(old)
    new = tmp_path / "Show Name.mkv"
    # The rename call succeeded but the folder still lists the old name.
    move = Move(
        source=old, destination=new, fingerprint=PlanFingerprint(new, st.st_size, st.st_mtime_ns)
    )
    outcome = ApplyOutcome(
        results=(), stragglers=(), moves=(move,), folders_created=(), folders_removed=()
    )

    undone = undo_apply(outcome)

    assert undone.results[0].status is ApplyStatus.RENAMED
    assert undone.results[0].reason == "already at its old place"
    assert undone.moves == ()
    assert os.listdir(tmp_path) == ["show name.mkv"]


def test_an_entry_that_already_had_its_name_is_not_touched(tmp_path: Path) -> None:
    show = _show(tmp_path)
    named = _write(_season(show) / "Show Name - S01E03 - Third.mkv", b"third")
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)
    assert all(m.destination != named for m in applied.moves)

    undo_apply(applied)

    assert listing(show) == before


def test_a_file_apply_left_behind_is_left_to_the_person(tmp_path: Path) -> None:
    copy = _write(tmp_path / "new" / "copy.mkv", b"copy")
    source = _write(tmp_path / "old" / "copy.mkv", b"copy")
    outcome = ApplyOutcome(
        results=(),
        stragglers=(),
        moves=(),
        folders_created=(tmp_path / "new",),
        folders_removed=(),
        files_left_behind=(copy,),
    )

    undone = undo_apply(outcome)

    assert copy.read_bytes() == b"copy"
    assert source.read_bytes() == b"copy"
    assert undone.folders_removed == ()


def test_an_apply_stopped_by_an_unexpected_error_is_undone_from_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _show(tmp_path)
    before = listing(show)
    plan = _plan(show)
    second = show / "Disc 2" / "Show.Name.S01E02.mkv"
    real = apply_module.move_no_replace

    def move(source: Path, dest: Path, changes: Changes) -> None:
        if source == second:
            raise RuntimeError("boom")
        real(source, dest, changes)

    monkeypatch.setattr(apply_module, "move_no_replace", move)
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()
    assert len(applied.moves) == 1

    undone = undo_apply(applied)

    assert listing(show) == before
    assert undone.put_back == 1


def test_an_unexpected_error_stops_undo_and_the_outcome_so_far_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    real = undo_module.move_no_replace
    calls: list[Path] = []

    def move(source: Path, dest: Path, changes: Changes, **kwargs: object) -> None:
        calls.append(source)
        if len(calls) == 2:
            raise RuntimeError("boom")
        real(source, dest, changes, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(undo_module, "move_no_replace", move)
    undone = undo_apply(applied)

    statuses = [(r.status, r.reason) for r in undone.results]
    assert statuses[0] == (ApplyStatus.RENAMED, "ok")
    assert statuses[1] == (ApplyStatus.FAIL, "unexpected error: RuntimeError('boom')")
    stopped = (ApplyStatus.SKIP, "not put back: Undo stopped after an unexpected error")
    assert statuses[2:] == [stopped] * (len(applied.moves) - 2)
    assert len(undone.moves) == 1
    # Only a folder Undo left empty is removed: the season folder holds the files left.
    assert _season(show).is_dir()
    assert _season(show) not in undone.folders_removed


def test_a_link_goes_back_as_itself_and_is_never_entered(tmp_path: Path) -> None:
    show = _show(tmp_path)
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "bonus.txt", b"bonus")
    _link_or_skip(show / "Disc 1" / "Extras", elsewhere)
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)
    assert (_season(show) / "Extras").is_symlink()

    undone = undo_apply(applied)

    assert listing(show) == before
    assert (show / "Disc 1" / "Extras").is_symlink()
    assert os.readlink(show / "Disc 1" / "Extras") == str(elsewhere)
    assert sorted(os.listdir(elsewhere)) == ["bonus.txt"]
    assert all(elsewhere not in r.source.parents for r in undone.results)


def test_a_file_whose_old_folder_is_now_a_link_is_left(tmp_path: Path) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    _link_or_skip(show / "Disc 2", elsewhere)

    undone = undo_apply(applied)

    moved = _season(show) / "Show Name - S01E02 - Second.mkv"
    assert _by_source(undone.results)[moved] == (
        ApplyStatus.SKIP,
        "its old folder is now a link or a file",
    )
    assert moved.exists()
    assert os.listdir(elsewhere) == []


def test_a_move_back_to_another_drive_is_a_checked_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _show(tmp_path)
    before = listing(show)
    applied = apply_plan(_plan(show), confirmed=True)

    def no_hard_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

    monkeypatch.setattr(os, "rename" if WINDOWS else "link", no_hard_link)
    undone = undo_apply(applied)
    monkeypatch.undo()

    if WINDOWS:
        # Windows renames even a case-only name, and a copy keeps the times it can set.
        assert undone.put_back == len(applied.moves)
    assert listing(show) == before
    assert undone.left == 0


def test_a_source_folder_named_like_its_new_folder_in_another_case_is_undone(
    tmp_path: Path,
) -> None:
    # A disk that keeps letter case apart makes "Show Name" beside "show name", and Apply
    # removes the emptied "show name"; one that ignores it moves into "show name".
    backups = tmp_path / "Backups"
    _write(backups / "show name" / "Show.Name.S01E01.mkv")
    _write(backups / "show name" / "notes.txt")
    backups = backups.resolve()
    before = listing(backups)
    applied = apply_plan(
        plan_queue([backups / "show name"], _options(destination_root=backups), _provider()).plan,
        confirmed=True,
    )
    assert listing(backups) != before

    undone = undo_apply(applied)

    assert listing(backups) == before
    assert undone.left == 0


def test_a_folder_apply_made_that_is_a_folder_it_removed_stays(tmp_path: Path) -> None:
    if not _ignores_letter_case(tmp_path):
        pytest.skip("on this filesystem two letter cases are two folders, never one")
    removed = tmp_path / "show name"
    made = tmp_path / "Show Name"
    outcome = ApplyOutcome(
        results=(), stragglers=(), moves=(), folders_created=(made,), folders_removed=(removed,)
    )

    undone = undo_apply(outcome)

    assert undone.folders_made_again == (removed,)
    assert undone.folders_removed == ()
    assert os.listdir(tmp_path) == ["show name"]


def test_the_check_of_a_file_is_the_last_look_before_its_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _show(tmp_path)
    applied = apply_plan(_plan(show), confirmed=True)
    notes = _season(show) / "notes.txt"
    real_lstat = os.lstat
    looks: list[bool] = []

    def lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        found = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        # The file changes just after move_no_replace's own look at what it is moving,
        # which comes before the file's last look.
        caller = sys._getframe(1).f_code.co_name
        if os.fspath(path) == str(notes) and caller == "move_no_replace" and not looks:  # type: ignore[call-overload]
            looks.append(True)
            notes.write_bytes(b"written as Undo looked at it")
        return found

    monkeypatch.setattr(os, "lstat", lstat)
    undone = undo_apply(applied)
    monkeypatch.undo()

    assert looks
    assert _by_source(undone.results)[notes][0] is ApplyStatus.SKIP
    assert notes.read_bytes() == b"written as Undo looked at it"
    assert not (show / "Disc 1" / "notes.txt").exists()
