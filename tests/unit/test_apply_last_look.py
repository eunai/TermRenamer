"""Apply's last look before each move: a source that changed since planning, a folder on
the way that is now a link, and a Straggler of another kind than the Plan listed are
skipped, and nothing is moved through a link (spec #16, section H)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyResult, ApplyStatus, Candidate, Plan
from termrenamer.core.planning import LeaveOut, PickMatch, PutBack, derive_plan, plan_queue

from .links import needs_symlinks, point_folder_at
from .test_apply_no_replace import _ignores_letter_case
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


def _unpoint(link: Path) -> None:
    """Remove the link or junction ``link``, never what it points to."""
    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)  # a junction is removed as an empty folder


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


def test_a_new_folder_that_was_a_link_when_the_plan_was_built_is_gone_through(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    library = tmp_path / "Library"
    library.mkdir()
    elsewhere = tmp_path / "Other Disk" / "Show Name"
    elsewhere.mkdir(parents=True)
    point_folder_at(library / "Show Name", elsewhere)
    options = _options(destination_root=library)
    plan = plan_queue([show], options, _provider()).plan
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    [dest] = [e.destination for e in plan.entries if e.source == video]
    assert dest is not None and library / "Show Name" in dest.parents

    outcome = apply_plan(plan, confirmed=True)

    assert _by_source(outcome.results)[video] == (ApplyStatus.RENAMED, "ok")
    assert (elsewhere / dest.relative_to(library / "Show Name")).read_bytes() == b"x"


def test_a_folder_straggler_made_a_link_after_part_of_it_moved_fails_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    subs = show / "Disc 1" / "Subs"
    _write(subs / "French.srt", b"fr")
    plan = _plan(show)
    [dest] = [s.destination for s in plan.stragglers if s.source == subs]
    assert dest is not None
    elsewhere = _write(tmp_path / "Elsewhere" / "bonus.srt", b"bonus").parent
    english = subs / "English.srt"
    as_it_was = tmp_path / "Subs as it was"
    done: list[bool] = []

    def after(real: object) -> object:
        def call(path: object, *args: object, **kwargs: object) -> object:
            out = real(path, *args, **kwargs)  # type: ignore[operator]
            if not done and os.fspath(path) == str(english):  # type: ignore[call-overload]
                done.append(True)  # English.srt has left: Subs is swapped for a link
                subs.rename(as_it_was)
                point_folder_at(subs, elsewhere)
            return out

        return call

    monkeypatch.setattr(os, "unlink", after(os.unlink))
    monkeypatch.setattr(os, "rename", after(os.rename))
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    status, reason = _by_source(outcome.stragglers)[subs]
    assert status == ApplyStatus.FAIL
    assert f"the folder {subs} is now a link" in reason and "part of the folder moved" in reason
    assert (dest / "English.srt").read_bytes() == b"x"
    assert (as_it_was / "French.srt").read_bytes() == b"fr"
    assert sorted(os.listdir(elsewhere)) == ["bonus.srt"]
    assert [m.source for m in outcome.moves if m.source.parent == subs] == [english]


def test_a_new_folder_made_a_link_after_the_preview_stays_one_in_a_derived_plan(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    plan = _plan(show)
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    [entry] = [e for e in plan.entries if e.source == video]
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    point_folder_at(show / "Show Name", elsewhere)
    # Left out and put back: its new name's folders are no new way to the derived Plan.
    left_out = derive_plan(plan, LeaveOut(entry))
    [out] = [e for e in left_out.entries if e.source == video]
    derived = derive_plan(left_out, PutBack(out))

    outcome = apply_plan(derived, confirmed=True)

    assert _by_source(outcome.results)[video] == _now_a_link(show / "Show Name")
    assert os.listdir(elsewhere) == []


def test_a_folder_that_was_a_link_pointed_elsewhere_after_the_preview_is_never_entered(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    library = tmp_path / "Library"
    library.mkdir()
    disk_a = tmp_path / "Disk A" / "Show Name"
    unrelated = tmp_path / "Unrelated" / "Show Name"
    disk_a.mkdir(parents=True)
    unrelated.mkdir(parents=True)
    point_folder_at(library / "Show Name", disk_a)
    plan = plan_queue([show], _options(destination_root=library), _provider()).plan
    _unpoint(library / "Show Name")
    point_folder_at(library / "Show Name", unrelated)

    outcome = apply_plan(plan, confirmed=True)

    another = (
        ApplyStatus.SKIP,
        f"the folder {library / 'Show Name'} is now another link than the Plan found",
    )
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    assert _by_source(outcome.results)[video] == another
    assert os.listdir(unrelated) == [] and os.listdir(disk_a) == []
    assert outcome.moves == ()


def test_a_folder_made_a_link_after_the_preview_and_reached_in_another_letter_case_is_not_entered(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    if not _ignores_letter_case(show):
        pytest.skip("needs a disk that ignores letter case")
    plan = _plan(show)
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    point_folder_at(show / "Show Name", elsewhere)
    [title] = plan.titles
    lower = Candidate(id="2", name="Show name", year=2010)
    episodes = {v.source: ("Pilot" if "E01" in v.source.name else "Second") for v in plan.videos}
    assert title.match is not None
    derived = derive_plan(
        plan, PickMatch(title, lower, found=(title.match, lower), episodes=episodes)
    )

    outcome = apply_plan(derived, confirmed=True)

    assert derived.linked_folders == ()
    assert all(r.status is not ApplyStatus.RENAMED for r in outcome.results)
    assert os.listdir(elsewhere) == []


def test_a_new_folder_apply_made_swapped_for_a_link_gets_no_folder_inside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    plan = _plan(show)
    made = show / "Show Name"
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()

    def swap() -> None:
        os.rmdir(made)
        point_folder_at(made, elsewhere)

    _when_made(monkeypatch, made, swap)
    outcome = apply_plan(plan, confirmed=True)
    monkeypatch.undo()

    assert os.listdir(elsewhere) == []
    video = show / "Disc 1" / "Show.Name.S01E01.mkv"
    assert _by_source(outcome.results)[video] == _now_a_link(made)
    assert outcome.moves == ()
