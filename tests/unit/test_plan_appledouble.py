"""A file found on the disk whose name starts with ``._`` is the companion file macOS
writes beside a file on a drive that cannot hold extended attributes (exFAT, FAT32, some
network shares). It is not the person's file: it is never a video, a Sidecar or a
Straggler, and Apply and Undo never move it by name. A name the Plan wrote is the
Plan's file whatever it starts with. The names are plain files on every system."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, Candidate, Plan
from termrenamer.core.planning import LeaveOut, PutBack, derive_plan, plan_queue
from termrenamer.core.undo import undo_apply

from .test_apply_no_replace import _with_the_number_of
from .test_plan_queue import TvStandIn
from .test_plan_stragglers import _options, _provider, _two_discs, _video_in, _write
from .test_undo import listing


def _with_companions(tmp_path: Path) -> Path:
    """Two discs of one show, a Sidecar, file and folder Stragglers, and the companion
    file macOS writes beside each of them and beside the ``Subs`` folder."""
    show = _two_discs(tmp_path)
    _write(show / "Disc 1" / "Show.Name.S01E01.srt", b"subs")
    for name in (
        "Disc 1/Show.Name.S01E01.mkv",
        "Disc 1/Show.Name.S01E01.srt",
        "Disc 1/folder.jpg",
        "Disc 1/notes.txt",
        "Disc 1/Subs",
        "Disc 1/Subs/English.srt",
        "Disc 2/Show.Name.S01E02.mkv",
        "Disc 2/folder.jpg",
    ):
        path = show.joinpath(*name.split("/"))
        _write(path.with_name("._" + path.name), b"\x00\x05\x16\x07 companion")
    return show


def _plan(show: Path) -> Plan:
    return plan_queue([show], _options(), _provider()).plan


def _companions(paths: object) -> list[Path]:
    return [p for p in paths if p.name.startswith("._")]  # type: ignore[attr-defined]


def test_a_companion_beside_a_video_is_not_a_video_and_takes_no_name(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)

    plan = _plan(show)

    season = show / "Show Name" / "Season 01"
    videos = [(e.source, e.destination) for e in plan.entries if not e.is_sidecar]
    assert videos == [
        (show / "Disc 1" / "Show.Name.S01E01.mkv", season / "Show Name - S01E01 - Pilot.mkv"),
        (show / "Disc 2" / "Show.Name.S01E02.mkv", season / "Show Name - S01E02 - Second.mkv"),
    ]


def test_a_companion_with_a_sidecars_extension_is_not_a_sidecar(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"

    for plan in (_plan(show), plan_queue([video], _options(), _provider()).plan):
        sidecars = [e.source for e in plan.entries if e.is_sidecar]
        assert sidecars == [show / "Disc 1" / "Show.Name.S01E01.srt"]


def test_a_companion_queued_by_itself_is_not_a_video(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)
    companion = show / "Disc 1" / "._Show.Name.S01E01.mkv"

    build = plan_queue([companion], _options(), _provider())

    assert build.plan.entries == ()
    assert build.messages == (f"Skipped {companion}: it is not a video.",)


def test_a_companion_is_not_a_straggler(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)

    plan = _plan(show)

    season = show / "Show Name" / "Season 01"
    assert [(s.source, s.destination) for s in plan.stragglers] == [
        (show / "Disc 1" / "folder.jpg", season / "folder.jpg"),
        (show / "Disc 1" / "notes.txt", season / "notes.txt"),
        (show / "Disc 1" / "Subs", season / "Subs"),
        (show / "Disc 2" / "folder.jpg", season / "folder (1).jpg"),
    ]
    assert all(_companions(folder.files) == [] for folder in plan.source_folders)


def test_a_derived_plan_with_companions_is_the_plan_a_fresh_build_makes(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)
    plan = _plan(show)

    left_out = derive_plan(plan, LeaveOut(_video_in(plan, "Disc 1")))
    put_back = derive_plan(left_out, PutBack(_video_in(left_out, "Disc 1")))

    assert _companions(s.source for s in left_out.stragglers) == []
    assert put_back == plan
    assert put_back == _plan(show)


def test_apply_and_undo_leave_every_companion_where_it_is(tmp_path: Path) -> None:
    show = _with_companions(tmp_path)
    before = listing(show)
    companions = sorted(_companions(show.rglob("*")))

    applied = apply_plan(_plan(show), confirmed=True)

    results = (*applied.results, *applied.stragglers)
    assert [r.status for r in results] == [ApplyStatus.RENAMED] * len(results)
    assert _companions(m.source for m in applied.moves) == []
    assert sorted(_companions(show.rglob("*"))) == companions  # each still at its place
    assert (show / "Disc 1" / "Subs" / "English.srt").exists() is False
    assert (show / "Show Name" / "Season 01" / "Subs" / "English.srt").exists()

    undone = undo_apply(applied)

    assert undone.put_back == len(applied.moves)
    assert undone.not_put_back == 0
    assert listing(show) == before


def test_a_folder_straggler_left_holding_only_companions_stays(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    extras = show / "Disc 1" / "Extras"
    _write(extras / "clip.txt", b"clip")
    _write(extras / "Deep" / "._clip.mkv", b"companion")
    before = listing(show)
    plan = _plan(show)
    assert extras in [s.source for s in plan.stragglers]

    applied = apply_plan(plan, confirmed=True)

    season = show / "Show Name" / "Season 01"
    by_source = {r.source: r.status for r in applied.stragglers}
    assert by_source[extras] is ApplyStatus.RENAMED
    assert (season / "Extras" / "clip.txt").read_bytes() == b"clip"
    assert sorted(p.name for p in extras.rglob("*")) == ["._clip.mkv", "Deep"]
    assert extras not in applied.folders_removed

    undone = undo_apply(applied)

    assert undone.put_back == len(applied.moves)
    assert listing(show) == before


def _removes_the_companion_with_its_file(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Removing a file, or renaming it, removes the companion file beside its old name,
    as macOS may on exFAT. Return the list of companion files the code under test named
    in a call that moves, copies or removes a file."""
    real_unlink, real_rename, real_link, real_open = os.unlink, os.rename, os.link, os.open
    named: list[Path] = []

    def note(*paths: object) -> None:
        named.extend(p for p in map(lambda q: Path(os.fspath(q)), paths) if p.name.startswith("._"))  # type: ignore[arg-type]

    def drop_companion(path: object) -> None:
        name = Path(os.fspath(path))  # type: ignore[call-overload]
        companion = name.with_name("._" + name.name)
        if os.path.lexists(companion):
            real_unlink(companion)

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        note(path)
        real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]
        drop_companion(path)

    def rename(src: object, dst: object, *args: object, **kwargs: object) -> None:
        note(src, dst)
        real_rename(src, dst, *args, **kwargs)  # type: ignore[arg-type]
        drop_companion(src)

    def link(src: object, dst: object, *args: object, **kwargs: object) -> None:
        note(src, dst)
        real_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    def open_(path: object, *args: object, **kwargs: object) -> int:
        note(path)
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "open", open_)
    return named


def test_a_folder_straggler_whose_companions_go_with_their_files_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _with_companions(tmp_path)
    subs = show / "Disc 1" / "Subs"
    plan = _plan(show)

    named = _removes_the_companion_with_its_file(monkeypatch)
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert named == []
    assert {r.source: r.status for r in applied.stragglers}[subs] is ApplyStatus.RENAMED
    assert not subs.exists()
    assert subs in applied.folders_removed


def test_a_companion_removed_with_its_file_during_a_folders_walk_stops_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    # "!" sorts before ".", so the file moves before the walk reaches its companion.
    _write(subs / "!track.txt", b"track")
    _write(subs / "._!track.txt", b"companion")
    _write(subs / "z-last.txt", b"last")
    plan = _plan(show)

    named = _removes_the_companion_with_its_file(monkeypatch)
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    new = show / "Show Name" / "Season 01" / "Subs"
    assert named == []
    assert {r.source: r.status for r in applied.stragglers}[subs] is ApplyStatus.RENAMED
    assert sorted(p.name for p in new.iterdir()) == ["!track.txt", "English.srt", "z-last.txt"]
    assert not subs.exists()


def test_undo_leaves_the_files_of_a_kept_folder_whose_place_another_folder_took(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "._lost.srt", b"companion")
    applied = apply_plan(_plan(show), confirmed=True)
    assert sorted(p.name for p in subs.iterdir()) == ["._lost.srt"]  # the folder stays

    subs.rename(tmp_path / "old Subs")
    subs.mkdir()  # another folder at its place
    undone = undo_apply(applied)

    moved = show / "Show Name" / "Season 01" / "Subs" / "English.srt"
    [result] = [r for r in undone.results if r.source == moved]
    assert (result.status, result.reason) == (
        ApplyStatus.SKIP,
        "its folder's old place is taken",
    )
    assert moved.exists()
    assert list(subs.iterdir()) == []


def test_a_name_the_plan_wrote_that_starts_like_a_companion_is_applied_and_undone(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    before = listing(show)
    provider = TvStandIn(
        shows={"show name": (Candidate(id="1", name="._Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )
    plan = plan_queue([show], _options(), provider).plan
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    [entry] = [e for e in plan.entries if e.source == video]
    assert entry.destination is not None and entry.destination.name.startswith("._")

    applied = apply_plan(plan, confirmed=True)

    assert {r.source: r.status for r in applied.results}[video] is ApplyStatus.RENAMED
    assert entry.destination.exists()

    undone = undo_apply(applied)

    assert undone.put_back == len(applied.moves)
    assert listing(show) == before


def test_undo_puts_files_back_into_a_kept_folder_whose_content_changed(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "._lost.srt", b"companion")
    applied = apply_plan(_plan(show), confirmed=True)
    (subs / "._lost.srt").unlink()  # its modification time changes; it is the same folder

    undone = undo_apply(applied)

    assert undone.not_put_back == 0
    assert (subs / "English.srt").exists()


def test_undo_takes_a_folder_made_again_with_the_kept_folders_number_for_it_and_overwrites_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stated limit: a folder made again under the same number is taken for the kept
    # one, and each old name is still claimed by the move itself.
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "French.srt", b"french")
    _write(subs / "._lost.srt", b"companion")
    applied = apply_plan(_plan(show), confirmed=True)
    kept = os.lstat(subs)
    subs.rename(tmp_path / "old Subs")
    _write(subs / "English.srt", b"another program's")
    real_lstat = os.lstat

    def lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        st = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        return _with_the_number_of(st, kept) if Path(os.fspath(path)) == subs else st  # type: ignore[call-overload]

    monkeypatch.setattr(os, "lstat", lstat)
    undone = undo_apply(applied)
    monkeypatch.undo()

    new = show / "Show Name" / "Season 01" / "Subs"
    reasons = {r.source.name: (r.status, r.reason) for r in undone.results}
    assert reasons["French.srt"] == (ApplyStatus.RENAMED, "ok")
    assert reasons["English.srt"] == (ApplyStatus.SKIP, "its old place is taken")
    assert (subs / "French.srt").read_bytes() == b"french"
    assert (subs / "English.srt").read_bytes() == b"another program's"
    assert (new / "English.srt").exists()


def test_undo_leaves_the_files_of_a_failed_walk_whose_folder_another_folder_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "z-fails.srt", b"fails")
    plan = _plan(show)
    real_link, real_rename = os.link, os.rename

    def refuse(real: object) -> object:
        def call(src: object, dst: object, *args: object, **kwargs: object) -> None:
            if Path(os.fspath(src)).name == "z-fails.srt":  # type: ignore[call-overload]
                raise OSError(errno.EIO, "Input/output error")
            real(src, dst, *args, **kwargs)  # type: ignore[operator]

        return call

    monkeypatch.setattr(os, "link", refuse(real_link))
    monkeypatch.setattr(os, "rename", refuse(real_rename))
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()
    assert {r.source: r.status for r in applied.stragglers}[subs] is ApplyStatus.FAIL
    assert subs in [k.path for k in applied.folders_kept]

    subs.rename(tmp_path / "old Subs")
    subs.mkdir()
    undone = undo_apply(applied)

    moved = show / "Show Name" / "Season 01" / "Subs" / "English.srt"
    [result] = [r for r in undone.results if r.source == moved]
    assert (result.status, result.reason) == (ApplyStatus.SKIP, "its folder's old place is taken")
    assert list(subs.iterdir()) == []


def test_a_folder_named_like_a_companion_that_vanishes_during_a_walk_fails_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "!first.txt", b"first")
    _write(subs / "._ordinary" / "inside.txt", b"inside")
    plan = _plan(show)
    real_unlink, real_rename = os.unlink, os.rename

    def then_remove_the_folder(real: object) -> object:
        def call(*args: object, **kwargs: object) -> None:
            real(*args, **kwargs)  # type: ignore[operator]
            if Path(os.fspath(args[0])).name == "!first.txt":  # type: ignore[call-overload]
                shutil.rmtree(subs / "._ordinary")

        return call

    monkeypatch.setattr(os, "unlink", then_remove_the_folder(real_unlink))
    monkeypatch.setattr(os, "rename", then_remove_the_folder(real_rename))
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert {r.source: r.status for r in applied.stragglers}[subs] is ApplyStatus.FAIL
