"""A file whose name starts with ``._`` is the companion file macOS writes beside a file
on a drive that cannot hold extended attributes (exFAT, FAT32, many network shares). It
is not the person's file: it is never a video, a Sidecar or a Straggler, and Apply and
Undo leave it where the system leaves it. The names are plain files on every system."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, Plan
from termrenamer.core.planning import LeaveOut, PutBack, derive_plan, plan_queue
from termrenamer.core.undo import undo_apply

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


def _removes_the_companion_with_its_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing a file removes the companion file beside it, as macOS does on exFAT."""
    real_unlink = os.unlink

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]
        name = Path(os.fspath(path))  # type: ignore[call-overload]
        companion = name.with_name("._" + name.name)
        if os.path.lexists(companion):
            real_unlink(companion)

    monkeypatch.setattr(os, "unlink", unlink)


def test_a_folder_straggler_whose_companions_go_with_their_files_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _with_companions(tmp_path)
    subs = show / "Disc 1" / "Subs"
    plan = _plan(show)

    _removes_the_companion_with_its_file(monkeypatch)
    applied = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert {r.source: r.status for r in applied.stragglers}[subs] is ApplyStatus.RENAMED
    assert not subs.exists()
    assert subs in applied.folders_removed
