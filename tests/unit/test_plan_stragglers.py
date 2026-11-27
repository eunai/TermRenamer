"""Stragglers are listed in the Plan: which children of a source folder they are, and the
paths the Plan fixes for them (spec #16, section C)."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import Candidate, Plan, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.core.policies import NameTakenPolicy

from .test_plan_queue import TvStandIn


def _options(*, folder_rename: bool = True, destination_root: Path | None = None) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=destination_root if folder_rename else None,
        folder_rename=folder_rename,
        season_folders=folder_rename,
    )


def _provider() -> TvStandIn:
    return TvStandIn(
        shows={"show name": (Candidate(id="1", name="Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second", ("1", 1, 3): "Third"},
    )


def _write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _stragglers(plan: Plan) -> list[tuple[Path, Path]]:
    return [(s.source, s.destination) for s in plan.stragglers]


def _two_discs(tmp_path: Path) -> Path:
    """One season on two discs, each with its own ``folder.jpg``; disc 1 also holds a
    ``Subs`` folder and a stray text file."""
    show = tmp_path / "Backups" / "Show Name"
    _write(show / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(show / "Disc 1" / "folder.jpg")
    _write(show / "Disc 1" / "notes.txt")
    _write(show / "Disc 1" / "Subs" / "English.srt")
    _write(show / "Disc 2" / "Show.Name.S01E02.mkv")
    _write(show / "Disc 2" / "folder.jpg")
    return show.resolve()


def test_the_plan_lists_the_children_left_in_a_folder_a_video_moves_out_of(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)

    plan = plan_queue([show], _options(), _provider()).plan

    season = show / "Show Name" / "Season 01"
    assert _stragglers(plan) == [
        (show / "Disc 1" / "folder.jpg", season / "folder.jpg"),
        (show / "Disc 1" / "notes.txt", season / "notes.txt"),
        (show / "Disc 1" / "Subs", season / "Subs"),
        (show / "Disc 2" / "folder.jpg", season / "folder (1).jpg"),
    ]


def test_the_plan_holds_the_children_of_each_folder_inside_a_folder_source(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)

    plan = plan_queue([show], _options(folder_rename=False), _provider()).plan

    assert [(f.path, f.children) for f in plan.source_folders] == [
        (
            show / "Disc 1",
            (
                show / "Disc 1" / "folder.jpg",
                show / "Disc 1" / "notes.txt",
                show / "Disc 1" / "Show.Name.S01E01.mkv",
                show / "Disc 1" / "Subs",
            ),
        ),
        (
            show / "Disc 2",
            (show / "Disc 2" / "folder.jpg", show / "Disc 2" / "Show.Name.S01E02.mkv"),
        ),
    ]


def test_with_folder_rename_off_the_plan_lists_no_stragglers(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)

    plan = plan_queue([show], _options(folder_rename=False), _provider()).plan

    assert plan.stragglers == ()


def test_the_files_beside_a_queued_file_source_are_never_stragglers(tmp_path: Path) -> None:
    folder = tmp_path / "Downloads"
    video = _write(folder / "Show.Name.S01E01.mkv")
    _write(folder / "folder.jpg")
    _write(folder / "Unrelated" / "notes.txt")

    plan = plan_queue([video], _options(), _provider()).plan

    [entry] = plan.entries
    assert entry.destination is not None
    assert entry.destination.parent != entry.source.parent
    assert plan.stragglers == ()
    assert plan.source_folders == ()


def test_a_file_source_inside_a_queued_folder_belongs_to_the_folder(tmp_path: Path) -> None:
    show = _two_discs(tmp_path)

    plan = plan_queue(
        [show / "Disc 2" / "Show.Name.S01E02.mkv", show], _options(), _provider()
    ).plan

    assert (show / "Disc 2" / "folder.jpg") in [s.source for s in plan.stragglers]


def test_a_video_that_is_not_applied_is_never_a_straggler_and_keeps_its_folder(
    tmp_path: Path,
) -> None:
    show = tmp_path / "Backups"
    _write(show / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(show / "Disc 1" / "Holiday Clip.mkv")
    _write(show / "Disc 1" / "Other.Show.S01E01.mkv")
    _write(show / "Disc 1" / "Show.Name.S01E07.mkv")
    _write(show / "Disc 1" / "folder.jpg")
    _write(show / "Disc 2" / "Other.Show.S01E02.mkv")
    _write(show / "Disc 2" / "folder.jpg")
    show = show.resolve()

    plan = plan_queue([show], _options(), _provider()).plan

    assert [s.source for s in plan.stragglers] == [show / "Disc 1" / "folder.jpg"]


def test_a_video_skipped_for_a_taken_name_is_never_a_straggler(tmp_path: Path) -> None:
    show = tmp_path / "Backups"
    _write(show / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(show / "Disc 1" / "Show.Name.S01E02.mkv")
    _write(show / "Show Name" / "Season 01" / "Show Name - S01E02 - Second.mkv", b"there")
    show = show.resolve()
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=True,
        season_folders=True,
        name_taken=NameTakenPolicy.SKIP,
    )

    plan = plan_queue([show], options, _provider()).plan

    assert plan.stragglers == ()


def test_a_child_folder_holding_an_entry_or_a_target_folder_is_never_a_straggler(
    tmp_path: Path,
) -> None:
    show = tmp_path / "Backups"
    _write(show / "Show.Name.S01E01.mkv")
    _write(show / "Extras" / "Show.Name.S01E02.mkv")
    _write(show / "Show Name" / "poster.jpg")
    _write(show / "Artwork" / "banner.jpg")
    _write(show / "notes.txt")
    show = show.resolve()

    plan = plan_queue([show], _options(), _provider()).plan

    season = show / "Show Name" / "Season 01"
    assert _stragglers(plan) == [
        (show / "Artwork", season / "Artwork"),
        (show / "notes.txt", season / "notes.txt"),
    ]


def test_a_straggler_path_that_is_taken_gets_a_number_whatever_name_taken_says(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    _write(show / "Show Name" / "Season 01" / "notes.txt", b"already there")
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=True,
        season_folders=True,
        name_taken=NameTakenPolicy.SKIP,
    )

    plan = plan_queue([show], options, _provider()).plan

    destinations = {s.source.name: s.destination.name for s in plan.stragglers}
    assert destinations["notes.txt"] == "notes (1).txt"


def test_a_straggler_goes_to_the_target_folder_that_sorts_first(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    _write(folder / "Mixed" / "Show.Name.S01E01.mkv")
    _write(folder / "Mixed" / "Another.Show.S02E05.mkv")
    _write(folder / "Mixed" / "folder.jpg")
    folder = folder.resolve()
    provider = TvStandIn(
        shows={
            "show name": (Candidate(id="1", name="Show Name", year=2010),),
            "another show": (Candidate(id="2", name="Another Show", year=2011),),
        },
        episodes={("1", 1, 1): "Pilot", ("2", 2, 5): "Mid"},
    )

    plan = plan_queue([folder], _options(), provider).plan

    assert _stragglers(plan) == [
        (folder / "Mixed" / "folder.jpg", folder / "Another Show" / "Season 02" / "folder.jpg"),
    ]


def test_a_straggler_never_takes_the_name_an_entry_claimed(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    _write(folder / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(folder / "Disc 1" / "Show.Name.S01E01.srt")
    _write(folder / "Disc 1" / "Show Name - S01E01 - Pilot.srt")
    folder = folder.resolve()

    plan = plan_queue([folder], _options(), _provider()).plan

    season = folder / "Show Name" / "Season 01"
    assert season / "Show Name - S01E01 - Pilot.srt" in [e.destination for e in plan.entries]
    assert _stragglers(plan) == [
        (
            folder / "Disc 1" / "Show Name - S01E01 - Pilot.srt",
            season / "Show Name - S01E01 - Pilot (1).srt",
        ),
    ]
