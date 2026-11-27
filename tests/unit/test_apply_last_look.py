"""Apply's last look before each move: a source that changed since planning, a folder on
the way that is now a link, and a Straggler of another kind than the Plan listed are
skipped, and nothing is moved through a link (spec #16, section H)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyResult, ApplyStatus, Plan
from termrenamer.core.planning import plan_queue

from .links import needs_symlinks, point_folder_at
from .test_plan_stragglers import _options, _provider, _two_discs, _write

STALE = (ApplyStatus.SKIP, "stale: source changed since plan")


def _by_source(results: tuple[ApplyResult, ...]) -> dict[Path, tuple[ApplyStatus, str]]:
    return {r.source: (r.status, r.reason) for r in results}


def _plan(show: Path) -> Plan:
    return plan_queue([show], _options(), _provider()).plan


def _when_made(monkeypatch: pytest.MonkeyPatch, folder: Path, then: object) -> None:
    """Run ``then`` once, just after Apply makes ``folder``."""
    real_mkdir = os.mkdir
    done: list[bool] = []

    def mkdir(path: object, *args: object, **kwargs: object) -> None:
        real_mkdir(path, *args, **kwargs)  # type: ignore[arg-type]
        if not done and os.fspath(path) == str(folder):  # type: ignore[call-overload]
            done.append(True)
            then()  # type: ignore[operator]

    monkeypatch.setattr(os, "mkdir", mkdir)


def test_a_video_written_while_its_new_folder_is_made_is_stale_and_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    plan = _plan(show)
    [dest] = [e.destination for e in plan.entries if e.source == video]
    assert dest is not None
    _when_made(monkeypatch, dest.parent, lambda: video.write_bytes(b"edited after the Preview"))

    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.results)[video] == STALE
    assert video.read_bytes() == b"edited after the Preview"
    assert not dest.exists(follow_symlinks=False)
    assert all(m.source != video for m in outcome.moves)


def test_a_video_that_is_a_link_is_moved_as_the_link_after_its_target_moved(
    tmp_path: Path,
) -> None:
    needs_symlinks(tmp_path)
    show = _two_discs(tmp_path)
    # The second episode is a link to the first, which Apply moves first.
    first = show / "Disc 1" / "Show.Name.S01E01.mkv"
    second = show / "Disc 2" / "Show.Name.S01E02.mkv"
    second.unlink()
    second.symlink_to(os.path.join(os.pardir, "Disc 1", first.name))
    target = os.readlink(second)
    plan = _plan(show)
    [dest] = [e.destination for e in plan.entries if e.source == second]
    assert dest is not None

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[second] == (ApplyStatus.RENAMED, "ok")
    assert dest.is_symlink()
    assert os.readlink(dest) == target
    [first_dest] = [e.destination for e in plan.entries if e.source == first]
    assert first_dest is not None
    assert first_dest.read_bytes() == b"x" and not first_dest.is_symlink()


def _now_a_link(folder: Path) -> tuple[ApplyStatus, str]:
    return (ApplyStatus.SKIP, f"the folder {folder} is now a link")


def test_a_new_folder_made_a_link_after_the_preview_is_never_entered(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan(show)
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    point_folder_at(show / "Show Name", elsewhere)

    outcome = apply_plan(plan, confirmed=True)

    for disc, video in (("Disc 1", "Show.Name.S01E01.mkv"), ("Disc 2", "Show.Name.S01E02.mkv")):
        source = show / disc / video
        assert _by_source(outcome.results)[source] == _now_a_link(show / "Show Name")
        assert source.read_bytes() == b"x"
    assert os.listdir(elsewhere) == []
    assert outcome.moves == ()
    assert outcome.folders_created == ()


def test_a_source_folder_made_a_link_after_the_preview_is_never_entered(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    disc_2 = show / "Disc 2"
    video = disc_2 / "Show.Name.S01E02.mkv"
    plan = _plan(show)
    # The same video, size and time included, in another folder that a link now stands for.
    elsewhere = _write(tmp_path / "Elsewhere" / video.name)
    st = os.stat(video)
    os.utime(elsewhere, ns=(st.st_atime_ns, st.st_mtime_ns))
    disc_2.rename(tmp_path / "Disc 2 as it was")
    point_folder_at(disc_2, elsewhere.parent)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[video] == _now_a_link(disc_2)
    assert elsewhere.read_bytes() == b"x"
    assert all(m.source != video for m in outcome.moves)


def test_a_folder_straggler_made_a_link_as_its_new_folder_is_made_is_never_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == subs]
    elsewhere = _write(tmp_path / "Elsewhere" / "bonus.srt", b"bonus").parent

    def swap() -> None:
        subs.rename(tmp_path / "Subs as it was")
        point_folder_at(subs, elsewhere)

    _when_made(monkeypatch, dest, swap)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert _by_source(outcome.stragglers)[subs] == _now_a_link(subs)
    assert sorted(os.listdir(elsewhere)) == ["bonus.srt"]
    assert all(elsewhere not in m.source.parents for m in outcome.moves)
    assert not (dest / "bonus.srt").exists()


def test_a_folder_straggler_that_is_a_link_at_apply_is_never_entered(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    plan = _plan(show)
    elsewhere = _write(tmp_path / "Elsewhere" / "bonus.srt", b"bonus").parent
    subs.rename(tmp_path / "Subs as it was")
    point_folder_at(subs, elsewhere)

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[subs] == _now_a_link(subs)
    assert sorted(os.listdir(elsewhere)) == ["bonus.srt"]
    assert all(elsewhere not in m.source.parents for m in outcome.moves)


def test_a_file_straggler_that_is_a_folder_at_apply_is_skipped(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    notes = show / "Disc 1" / "notes.txt"
    plan = _plan(show)
    notes.unlink()
    _write(notes / "Another.Show.S01E01.mkv", b"not in the Plan")

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[notes] == (
        ApplyStatus.SKIP,
        "stale: the Plan listed a file and a folder is there now",
    )
    assert (notes / "Another.Show.S01E01.mkv").read_bytes() == b"not in the Plan"
    assert all(notes not in m.source.parents for m in outcome.moves)


def test_a_folder_straggler_that_is_a_file_at_apply_is_skipped(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    plan = _plan(show)
    (subs / "English.srt").unlink()
    subs.rmdir()
    _write(subs, b"a file now")

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.stragglers)[subs] == (
        ApplyStatus.SKIP,
        "stale: the Plan listed a folder and a file is there now",
    )
    assert subs.read_bytes() == b"a file now"
