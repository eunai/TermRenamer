"""Apply moves the Stragglers the Plan lists and nothing else, and returns an outcome that
records every move and every folder it made or removed (spec #16, section H)."""

from __future__ import annotations

import os
from pathlib import Path

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, Candidate, Plan, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue

from .test_plan_queue import TvStandIn
from .test_plan_stragglers import _options, _provider, _two_discs, _write


def _plan(sources: list[Path], options: PlanOptions | None = None) -> Plan:
    return plan_queue(sources, options or _options(), _provider()).plan


def _tree(root: Path) -> set[Path]:
    """Every file and folder under ``root``."""
    return set(root.rglob("*"))


def test_apply_merges_the_listed_stragglers_and_removes_the_emptied_folders(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])

    outcome = apply_plan(plan, confirmed=True)

    season = show / "Show Name" / "Season 01"
    assert _tree(show) == {
        show / "Show Name",
        season,
        season / "Show Name - S01E01 - Pilot.mkv",
        season / "Show Name - S01E02 - Second.mkv",
        season / "Subs",
        season / "Subs" / "English.srt",
        season / "folder (1).jpg",
        season / "folder.jpg",
        season / "notes.txt",
    }
    assert [(r.source, r.destination, r.status, r.reason) for r in outcome.stragglers] == [
        (s.source, s.destination, ApplyStatus.RENAMED, "ok") for s in plan.stragglers
    ]
    # The Subs folder is moved as its files: made again at its new place, then removed.
    assert outcome.folders_created == (show / "Show Name", season, season / "Subs")
    assert outcome.folders_removed == (show / "Disc 1" / "Subs", show / "Disc 1", show / "Disc 2")


def test_the_outcome_records_each_move_with_the_size_and_time_at_its_new_place(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])

    outcome = apply_plan(plan, confirmed=True)

    season = show / "Show Name" / "Season 01"
    planned = [(e.source, e.destination) for e in plan.entries]
    for s in plan.stragglers:
        if s.source.name == "Subs":  # a folder is moved as its files
            planned.append((s.source / "English.srt", season / "Subs" / "English.srt"))
        else:
            planned.append((s.source, s.destination))
    assert [(m.source, m.destination) for m in outcome.moves] == planned
    for move in outcome.moves:
        st = os.lstat(move.destination)
        assert (move.fingerprint.path, move.fingerprint.size, move.fingerprint.mtime_ns) == (
            move.destination,
            st.st_size,
            st.st_mtime_ns,
        )
    assert [(r.source, r.status) for r in outcome.results] == [
        (e.source, ApplyStatus.RENAMED) for e in plan.entries
    ]


def test_a_file_that_appears_after_planning_is_never_moved(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])
    late = _write(show / "Disc 1" / "added later.txt")

    outcome = apply_plan(plan, confirmed=True)

    assert late.read_bytes() == b"x"
    assert sorted(p.name for p in (show / "Disc 1").iterdir()) == ["added later.txt"]
    assert show / "Disc 1" not in outcome.folders_removed
    assert all(m.source != late for m in outcome.moves)


def test_the_files_beside_a_queued_file_source_stay_where_they_are(tmp_path: Path) -> None:
    folder = tmp_path / "Downloads"
    video = _write(folder / "Show.Name.S01E01.mkv")
    _write(folder / "folder.jpg")
    _write(folder / "Unrelated" / "notes.txt")

    apply_plan(_plan([video]), confirmed=True)

    folder = folder.resolve()
    season = folder / "Show Name" / "Season 01"
    assert _tree(folder) == {
        folder / "Show Name",
        season,
        season / "Show Name - S01E01 - Pilot.mkv",
        folder / "Unrelated",
        folder / "Unrelated" / "notes.txt",
        folder / "folder.jpg",
    }


def test_a_video_with_no_match_stays_in_its_folder_and_is_not_merged(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    _write(folder / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(folder / "Disc 1" / "Other.Show.S01E01.mkv", b"o")
    _write(folder / "Disc 1" / "Holiday Clip.mkv", b"h")
    _write(folder / "Disc 1" / "folder.jpg")
    folder = folder.resolve()

    apply_plan(_plan([folder]), confirmed=True)

    assert sorted(p.name for p in (folder / "Disc 1").iterdir()) == [
        "Holiday Clip.mkv",
        "Other.Show.S01E01.mkv",
    ]
    assert (folder / "Show Name" / "Season 01" / "folder.jpg").is_file()


def test_a_straggler_moves_only_when_an_entry_from_its_folder_moved(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])
    _write(show / "Disc 2" / "Show.Name.S01E02.mkv", b"changed since planning")

    outcome = apply_plan(plan, confirmed=True)

    assert sorted(p.name for p in (show / "Disc 2").iterdir()) == [
        "Show.Name.S01E02.mkv",
        "folder.jpg",
    ]
    by_source = {r.source: (r.status, r.reason) for r in outcome.stragglers}
    assert by_source[show / "Disc 2" / "folder.jpg"] == (
        ApplyStatus.SKIP,
        "nothing moved out of its folder",
    )
    assert by_source[show / "Disc 1" / "folder.jpg"] == (ApplyStatus.RENAMED, "ok")


def test_a_straggler_gone_since_planning_is_skipped(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])
    (show / "Disc 1" / "notes.txt").unlink()

    outcome = apply_plan(plan, confirmed=True)

    by_source = {r.source: (r.status, r.reason) for r in outcome.stragglers}
    assert by_source[show / "Disc 1" / "notes.txt"] == (ApplyStatus.SKIP, "stale: source missing")
    assert not (show / "Show Name" / "Season 01" / "notes.txt").exists()


def test_a_straggler_whose_path_is_taken_at_apply_time_is_skipped(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show])
    _write(show / "Show Name" / "Season 01" / "notes.txt", b"arrived after planning")

    outcome = apply_plan(plan, confirmed=True)

    by_source = {r.source: (r.status, r.reason) for r in outcome.stragglers}
    assert by_source[show / "Disc 1" / "notes.txt"] == (
        ApplyStatus.SKIP,
        "destination exists at apply time",
    )
    assert (show / "Disc 1" / "notes.txt").read_bytes() == b"x"
    assert (show / "Show Name" / "Season 01" / "notes.txt").read_bytes() == (
        b"arrived after planning"
    )
    assert show / "Disc 1" not in outcome.folders_removed


def test_with_folder_rename_off_apply_merges_nothing(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)
    plan = _plan([show], _options(folder_rename=False))

    outcome = apply_plan(plan, confirmed=True)

    assert outcome.stragglers == ()
    assert outcome.folders_created == ()
    assert outcome.folders_removed == ()
    assert sorted(p.name for p in (show / "Disc 1").iterdir()) == [
        "Show Name - S01E01 - Pilot.mkv",
        "Subs",
        "folder.jpg",
        "notes.txt",
    ]


def test_plan_options_are_read_from_the_plan_and_apply_takes_no_straggler_flag() -> None:
    import inspect

    assert list(inspect.signature(apply_plan).parameters) == ["plan", "confirmed"]


def test_a_straggler_bound_for_a_target_folder_no_entry_made_gets_it_made(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Backups"
    _write(folder / "Mixed" / "Show.Name.S01E01.mkv")
    _write(folder / "Mixed" / "Another.Show.S02E05.mkv")
    _write(folder / "Mixed" / "folder.jpg")
    folder = folder.resolve()
    library = folder / "Library"
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=library,
        folder_rename=True,
        season_folders=True,
    )
    provider = TvStandIn(
        shows={
            "show name": (Candidate(id="1", name="Show Name", year=2010),),
            "another show": (Candidate(id="2", name="Another Show", year=2011),),
        },
        episodes={("1", 1, 1): "Pilot", ("2", 2, 5): "Mid"},
    )
    plan = plan_queue([folder], options, provider).plan
    [straggler] = plan.stragglers
    assert straggler.destination == library / "Another Show" / "Season 02" / "folder.jpg"
    _write(folder / "Mixed" / "Another.Show.S02E05.mkv", b"changed since planning")

    outcome = apply_plan(plan, confirmed=True)

    assert straggler.destination.is_file()
    assert outcome.folders_created == (
        library,
        library / "Show Name",
        library / "Show Name" / "Season 01",
        library / "Another Show",
        library / "Another Show" / "Season 02",
    )
    assert outcome.folders_removed == ()
