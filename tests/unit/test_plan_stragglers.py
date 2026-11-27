"""Stragglers are listed in the Plan: which children of a source folder they are, and the
paths the Plan fixes for them (spec #16, section C)."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.core.models import (
    Candidate,
    EntryStatus,
    Plan,
    PlanEntry,
    PlanFingerprint,
    PlanOptions,
    ScanMode,
    SourceFolder,
)
from termrenamer.core.paths import path_key
from termrenamer.core.planning import LeaveOut, PutBack, derive_plan, plan_queue
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.core.stragglers import plan_stragglers

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
    ``Subs`` folder and a text file of notes."""
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

    disc_1, disc_2 = show / "Disc 1", show / "Disc 2"
    assert [(f.path, f.files, f.folders) for f in plan.source_folders] == [
        (
            disc_1,
            (disc_1 / "folder.jpg", disc_1 / "notes.txt", disc_1 / "Show.Name.S01E01.mkv"),
            (disc_1 / "Subs",),
        ),
        (disc_2, (disc_2 / "folder.jpg", disc_2 / "Show.Name.S01E02.mkv"), ()),
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
    assert path_key(entry.destination.parent) != path_key(entry.source.parent)
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


def test_a_file_in_a_folder_inside_its_target_folder_is_a_straggler(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    _write(folder / "Show Name" / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(folder / "Show Name" / "Disc 1" / "folder.jpg")
    _write(folder / "Show Name" / "Disc 1" / "Subs" / "English.srt")
    folder = folder.resolve()
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=True,
        season_folders=False,
    )

    plan = plan_queue([folder], options, _provider()).plan

    [entry] = plan.entries
    assert entry.destination == folder / "Show Name" / "Show Name - S01E01 - Pilot.mkv"
    assert _stragglers(plan) == [
        (folder / "Show Name" / "Disc 1" / "folder.jpg", folder / "Show Name" / "folder.jpg"),
    ]


def test_the_folder_of_a_video_that_already_has_its_name_is_no_target_folder(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Backups"
    season = folder / "Show Name" / "Season 01"
    _write(season / "Show Name - S01E01 - Pilot.mkv")
    _write(season / "Another.Show.S02E05.mkv")
    _write(season / "Subs" / "English.srt")
    folder = folder.resolve()
    season = season.resolve()
    provider = TvStandIn(
        shows={
            "show name": (Candidate(id="1", name="Show Name", year=2010),),
            "another show": (Candidate(id="2", name="Another Show", year=2011),),
        },
        episodes={("1", 1, 1): "Pilot", ("2", 2, 5): "Mid"},
    )

    plan = plan_queue([folder], _options(), provider).plan

    assert [e.has_its_name for e in plan.entries] == [False, True]
    assert _stragglers(plan) == [
        (season / "Subs", folder / "Another Show" / "Season 02" / "Subs"),
    ]


def test_two_stragglers_whose_names_differ_only_in_letter_case_never_share_a_path(
    tmp_path: Path,
) -> None:
    show = tmp_path / "Backups" / "Show Name"
    _write(show / "Disc 1" / "Show.Name.S01E01.mkv")
    _write(show / "Disc 1" / "Folder.jpg")
    _write(show / "Disc 2" / "Show.Name.S01E02.mkv")
    _write(show / "Disc 2" / "folder.jpg")
    show = show.resolve()

    plan = plan_queue([show], _options(), _provider()).plan

    season = show / "Show Name" / "Season 01"
    assert _stragglers(plan) == [
        (show / "Disc 1" / "Folder.jpg", season / "Folder.jpg"),
        (show / "Disc 2" / "folder.jpg", season / "folder (1).jpg"),
    ]


def _video_in(plan: Plan, folder: str) -> PlanEntry:
    [video] = [e for e in plan.entries if not e.is_sidecar and e.source.parent.name == folder]
    return video


def test_leaving_out_the_only_video_a_folder_moves_turns_its_stragglers_off_and_back_on(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    plan = plan_queue([show], _options(), _provider()).plan

    left_out = derive_plan(plan, LeaveOut(_video_in(plan, "Disc 1")))
    put_back = derive_plan(left_out, PutBack(_video_in(left_out, "Disc 1")))

    season = show / "Show Name" / "Season 01"
    # Disc 1's children stay; Disc 2's folder.jpg now claims the plain name.
    assert _stragglers(left_out) == [(show / "Disc 2" / "folder.jpg", season / "folder.jpg")]
    assert all(s.source != _video_in(plan, "Disc 1").source for s in left_out.stragglers)
    assert left_out.source_folders == plan.source_folders
    assert put_back == plan


def test_deriving_works_out_the_stragglers_without_reading_a_folder_or_resolving_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = _two_discs(tmp_path)
    plan = plan_queue([show], _options(), _provider()).plan

    def no_resolve(self: Path, strict: bool = False) -> Path:
        raise AssertionError(f"resolved {self} while deriving")

    def no_listing(self: Path) -> object:
        raise AssertionError(f"listed {self} while deriving")

    monkeypatch.setattr(Path, "resolve", no_resolve)
    monkeypatch.setattr(Path, "iterdir", no_listing)
    left_out = derive_plan(plan, LeaveOut(_video_in(plan, "Disc 2")))
    put_back = derive_plan(left_out, PutBack(_video_in(left_out, "Disc 2")))
    monkeypatch.undo()

    assert [s.source.parent.name for s in left_out.stragglers] == ["Disc 1"] * 3
    assert put_back == plan


def test_two_stragglers_whose_names_differ_only_in_unicode_form_never_share_a_path(
    tmp_path: Path,
) -> None:
    composed, decomposed = "café.jpg", "café.jpg"
    show = _two_discs(tmp_path)
    _write(show / "Disc 1" / composed)
    _write(show / "Disc 2" / decomposed)

    plan = plan_queue([show], _options(), _provider()).plan

    season = show / "Show Name" / "Season 01"
    names = {s.source.parent.name: s.destination for s in plan.stragglers if "caf" in s.source.name}
    assert names == {
        "Disc 1": season / composed,
        "Disc 2": season / "café (1).jpg",
    }


def _entry_moving_to(source: Path, destination: Path) -> PlanEntry:
    return PlanEntry(
        source=source,
        destination=destination,
        status=EntryStatus.READY,
        title=None,
        video=None,
        season=1,
        episode=1,
        root=source.parent.parent,
        fingerprint=PlanFingerprint(path=source, size=1, mtime_ns=0),
    )


def test_two_source_folders_whose_names_differ_only_in_letter_case_stay_two(
    tmp_path: Path,
) -> None:
    # As a case-sensitive filesystem holds them; the Plan's records alone, no disk.
    upper, lower = tmp_path / "Backups" / "Disc", tmp_path / "Backups" / "disc"
    alpha = tmp_path / "Library" / "Alpha" / "Season 01"
    beta = tmp_path / "Library" / "Beta" / "Season 01"
    entries = [
        _entry_moving_to(upper / "Alpha.S01E01.mkv", alpha / "Alpha - S01E01.mkv"),
        _entry_moving_to(lower / "Beta.S01E01.mkv", beta / "Beta - S01E01.mkv"),
    ]
    folders = [
        SourceFolder(
            path=upper, files=(upper / "Alpha.S01E01.mkv", upper / "alpha.jpg"), folders=()
        ),
        SourceFolder(path=lower, files=(lower / "Beta.S01E01.mkv", lower / "beta.jpg"), folders=()),
    ]

    stragglers = plan_stragglers(_options(), entries, folders)

    assert _stragglers(Plan(options=_options(), titles=(), entries=(), stragglers=stragglers)) == [
        (upper / "alpha.jpg", alpha / "alpha.jpg"),
        (lower / "beta.jpg", beta / "beta.jpg"),
    ]
