"""Apply a Plan from the core entry point: what it renames, skips and leaves alone."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    EpisodeMetadata,
    Plan,
    PlanOptions,
    ScanMode,
)
from termrenamer.core.planning import plan_queue


def _provider() -> StaticTvMetadataProvider:
    return StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
            ("show name", 1, 2): EpisodeMetadata(show_title="Show Name", episode_title="Second"),
            ("another show", 2, 5): EpisodeMetadata(show_title="Another Show", episode_title="Mid"),
        },
    )


def _plan(sources: list[Path], *, folder_rename: bool = False) -> Plan:
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=folder_rename,
        season_folders=folder_rename,
    )
    return plan_queue(sources, options, _provider()).plan


def _by_name(results: list[ApplyResult]) -> dict[str, tuple[ApplyStatus, str]]:
    return {r.source.name: (r.status, r.reason) for r in results}


def test_apply_leaves_no_match_and_not_recognised_files_and_their_sidecars(
    tmp_path: Path,
) -> None:
    names = [
        "Holiday Clip.mkv",
        "Holiday Clip.srt",
        "Other.Show.S01E01.mkv",
        "Other.Show.S01E01.srt",
    ]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"v")

    results = apply_plan(_plan([tmp_path], folder_rename=True), confirmed=True)

    assert _by_name(results) == {
        "Holiday Clip.mkv": (ApplyStatus.SKIP, "not recognised"),
        "Holiday Clip.srt": (ApplyStatus.SKIP, "not recognised"),
        "Other.Show.S01E01.mkv": (ApplyStatus.SKIP, "no match"),
        "Other.Show.S01E01.srt": (ApplyStatus.SKIP, "no match"),
        "Show.Name.S01E01.mkv": (ApplyStatus.RENAMED, "ok"),
    }
    for name in names:
        assert (tmp_path / name).read_bytes() == b"x", f"{name} must stay where it was"


def test_a_sidecar_is_applied_after_its_video_and_only_when_the_video_moved(
    tmp_path: Path,
) -> None:
    for stem in ("Show.Name.S01E01", "Show.Name.S01E02"):
        (tmp_path / f"{stem}.mkv").write_bytes(b"v")
        (tmp_path / f"{stem}.idx").write_bytes(b"i")
    plan = _plan([tmp_path])
    (tmp_path / "Show.Name.S01E02.mkv").write_bytes(b"changed since planning")

    results = apply_plan(plan, confirmed=True)

    assert [r.source.name for r in results] == [
        "Show.Name.S01E01.mkv",
        "Show.Name.S01E02.mkv",
        "Show.Name.S01E01.idx",
        "Show.Name.S01E02.idx",
    ]
    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.RENAMED, "ok"),
        "Show.Name.S01E02.mkv": (ApplyStatus.SKIP, "stale: source changed since plan"),
        "Show.Name.S01E01.idx": (ApplyStatus.RENAMED, "ok"),
        "Show.Name.S01E02.idx": (ApplyStatus.SKIP, "video not applied"),
    }
    assert (tmp_path / "Show Name - S01E01 - Pilot.idx").read_bytes() == b"i"
    assert (tmp_path / "Show.Name.S01E02.idx").read_bytes() == b"i"


def test_an_entry_already_at_its_name_is_unchanged_and_its_sidecar_still_moves(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show Name - S01E01 - Pilot.mkv").write_bytes(b"v")
    (tmp_path / "Show Name - S01E01 - Pilot.SRT").write_bytes(b"s")

    results = apply_plan(_plan([tmp_path]), confirmed=True)

    assert _by_name(results) == {
        "Show Name - S01E01 - Pilot.mkv": (ApplyStatus.UNCHANGED, "already has its name"),
        "Show Name - S01E01 - Pilot.SRT": (ApplyStatus.RENAMED, "ok"),
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Show Name - S01E01 - Pilot.mkv",
        "Show Name - S01E01 - Pilot.srt",
    ]


def test_apply_merges_stragglers_by_the_folder_rename_value_the_plan_was_built_with(
    tmp_path: Path,
) -> None:
    for folder_rename in (True, False):
        season = tmp_path / str(folder_rename) / "Disc 1"
        season.mkdir(parents=True)
        (season / "Show.Name.S01E01.mkv").write_bytes(b"v")
        (season / "notes.txt").write_text("n", encoding="utf-8")
        plan = _plan([tmp_path / str(folder_rename)], folder_rename=folder_rename)

        apply_plan(plan, confirmed=True)

        [entry] = plan.entries
        assert entry.destination is not None and entry.destination.is_file()
        if folder_rename:
            assert (entry.destination.parent / "notes.txt").is_file()
            assert not season.exists()
        else:
            assert sorted(p.name for p in season.iterdir()) == [
                "Show Name - S01E01 - Pilot.mkv",
                "notes.txt",
            ]


def test_stragglers_never_include_files_of_the_plan_that_apply_does_not_move(
    tmp_path: Path,
) -> None:
    season = tmp_path / "Disc 1"
    season.mkdir()
    (season / "Show.Name.S01E01.mkv").write_bytes(b"v")
    (season / "Holiday Clip.mkv").write_bytes(b"h")
    (season / "Other.Show.S01E01.mkv").write_bytes(b"o")
    (season / "Show.Name.S01E02.mkv").write_bytes(b"w")
    plan = _plan([tmp_path], folder_rename=True)
    (season / "Show.Name.S01E02.mkv").write_bytes(b"changed")

    apply_plan(plan, confirmed=True)

    assert sorted(p.name for p in season.iterdir()) == [
        "Holiday Clip.mkv",
        "Other.Show.S01E01.mkv",
        "Show.Name.S01E02.mkv",
    ]


def test_stragglers_never_include_a_target_folder_or_a_folder_inside_one(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"v")
    (tmp_path / "Another.Show.S02E05.mkv").write_bytes(b"w")
    (tmp_path / "notes.txt").write_text("n", encoding="utf-8")
    plan = _plan([tmp_path], folder_rename=True)

    apply_plan(plan, confirmed=True)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["Another Show", "Show Name"]
    assert sorted(p.name for p in (tmp_path / "Show Name" / "Season 01").iterdir()) == [
        "Show Name - S01E01 - Pilot.mkv",
    ]
    assert sorted(p.name for p in (tmp_path / "Another Show" / "Season 02").iterdir()) == [
        "Another Show - S02E05 - Mid.mkv",
        "notes.txt",
    ]


def test_a_sidecar_changed_since_planning_is_skipped_while_its_video_moves(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"v")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    plan = _plan([tmp_path])
    (tmp_path / "Show.Name.S01E01.srt").write_text("edited since planning", encoding="utf-8")

    results = apply_plan(plan, confirmed=True)

    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.RENAMED, "ok"),
        "Show.Name.S01E01.srt": (ApplyStatus.SKIP, "stale: source changed since plan"),
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Show Name - S01E01 - Pilot.mkv",
        "Show.Name.S01E01.srt",
    ]
