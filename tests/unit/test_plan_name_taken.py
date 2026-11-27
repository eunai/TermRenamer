"""Name taken in the Plan: ``suffix`` numbers a taken name, ``skip`` leaves the file where it is.

Real temporary folders and a stand-in Provider, through :func:`plan_queue`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from termrenamer.core.models import Candidate, EntryStatus, Plan, PlanEntry, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.core.policies import CollisionPolicy

PILOT = "Show Name - S01E01 - Pilot"


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data."""

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return self.episodes.get((show_id, season, episode))


def _show_name() -> TvStandIn:
    return TvStandIn(
        shows={"show name": (Candidate(id="1", name="Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )


def _options(
    policy: CollisionPolicy | None, *, library: Path | None = None, **kwargs: object
) -> PlanOptions:
    values: dict[str, object] = {
        "mode": ScanMode.TV,
        "provider_id": "tmdb",
        "destination_root": library,
        "folder_rename": library is not None,
        "season_folders": False,
    }
    if policy is not None:
        values["name_taken"] = policy
    values.update(kwargs)
    return PlanOptions(**values)  # type: ignore[arg-type]


def _by_name(plan: Plan) -> dict[str, PlanEntry]:
    return {e.source.name: e for e in plan.entries}


def _two_discs(tmp_path: Path) -> list[Path]:
    """Disc A and Disc B each hold the Pilot with its subtitle; Disc B is queued first."""
    for disc in ("Disc A", "Disc B"):
        (tmp_path / disc).mkdir()
        (tmp_path / disc / "Show.Name.S01E01.mkv").write_bytes(disc.encode())
        (tmp_path / disc / "Show.Name.S01E01.srt").write_text(disc, encoding="utf-8")
    return [tmp_path / "Disc B", tmp_path / "Disc A"]


def _summary(plan: Plan) -> list[tuple[str, str, str | None, EntryStatus]]:
    return [
        (
            e.source.parent.name,
            e.source.name,
            e.destination.name if e.destination is not None else None,
            e.status,
        )
        for e in plan.entries
    ]


def test_suffix_is_the_default_and_gives_the_numbered_names_of_today(tmp_path: Path) -> None:
    library = tmp_path / "Library"
    (library / "Show Name").mkdir(parents=True)
    (library / "Show Name" / f"{PILOT}.mkv").write_bytes(b"already there")
    queue = _two_discs(tmp_path)

    default = plan_queue(queue, _options(None, library=library), _show_name()).plan
    suffix = plan_queue(queue, _options(CollisionPolicy.SUFFIX, library=library), _show_name()).plan

    assert default.options.name_taken is CollisionPolicy.SUFFIX
    assert (
        _summary(default)
        == _summary(suffix)
        == [
            ("Disc A", "Show.Name.S01E01.mkv", f"{PILOT} (1).mkv", EntryStatus.NAME_TAKEN),
            ("Disc A", "Show.Name.S01E01.srt", f"{PILOT} (1).srt", EntryStatus.READY),
            ("Disc B", "Show.Name.S01E01.mkv", f"{PILOT} (2).mkv", EntryStatus.NAME_TAKEN),
            ("Disc B", "Show.Name.S01E01.srt", f"{PILOT} (2).srt", EntryStatus.READY),
        ]
    )


def test_under_skip_a_name_taken_on_disk_leaves_the_video_and_its_sidecar_unapplied(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    (library / "Show Name").mkdir(parents=True)
    (library / "Show Name" / f"{PILOT}.mkv").write_bytes(b"already there")
    queue = _two_discs(tmp_path)

    plan = plan_queue(queue, _options(CollisionPolicy.SKIP, library=library), _show_name()).plan

    assert plan.options.name_taken is CollisionPolicy.SKIP
    assert _summary(plan) == [
        ("Disc A", "Show.Name.S01E01.mkv", None, EntryStatus.NAME_TAKEN),
        ("Disc A", "Show.Name.S01E01.srt", None, EntryStatus.NAME_TAKEN),
        ("Disc B", "Show.Name.S01E01.mkv", None, EntryStatus.NAME_TAKEN),
        ("Disc B", "Show.Name.S01E01.srt", None, EntryStatus.NAME_TAKEN),
    ]


def test_under_skip_the_first_entry_in_source_path_order_claims_the_name(tmp_path: Path) -> None:
    library = tmp_path / "Library"
    queue = _two_discs(tmp_path)

    plan = plan_queue(queue, _options(CollisionPolicy.SKIP, library=library), _show_name()).plan

    assert _summary(plan) == [
        ("Disc A", "Show.Name.S01E01.mkv", f"{PILOT}.mkv", EntryStatus.READY),
        ("Disc A", "Show.Name.S01E01.srt", f"{PILOT}.srt", EntryStatus.READY),
        ("Disc B", "Show.Name.S01E01.mkv", None, EntryStatus.NAME_TAKEN),
        ("Disc B", "Show.Name.S01E01.srt", None, EntryStatus.NAME_TAKEN),
    ]


def test_under_skip_a_sidecar_whose_own_name_is_taken_is_skipped_alone(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Show.Name.S01E01.nfo").write_text("n", encoding="utf-8")
    (tmp_path / f"{PILOT}.srt").write_text("old", encoding="utf-8")

    plan = plan_queue([tmp_path], _options(CollisionPolicy.SKIP), _show_name()).plan

    root = tmp_path.resolve()
    entries = _by_name(plan)
    video = entries["Show.Name.S01E01.mkv"]
    assert (video.destination, video.status) == (root / f"{PILOT}.mkv", EntryStatus.READY)
    srt = entries["Show.Name.S01E01.srt"]
    assert (srt.destination, srt.status) == (None, EntryStatus.NAME_TAKEN)
    nfo = entries["Show.Name.S01E01.nfo"]
    assert (nfo.destination, nfo.status) == (root / f"{PILOT}.nfo", EntryStatus.READY)


def test_a_file_already_at_its_name_is_not_taken_by_itself_under_skip(tmp_path: Path) -> None:
    (tmp_path / f"{PILOT}.mkv").write_bytes(b"a")

    plan = plan_queue([tmp_path], _options(CollisionPolicy.SKIP), _show_name()).plan

    [entry] = plan.entries
    assert (entry.destination, entry.status) == (entry.source, EntryStatus.READY)


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges on Windows")
def test_under_skip_a_broken_link_at_the_wanted_name_counts_as_taken(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / f"{PILOT}.mkv").symlink_to(tmp_path / "gone.mkv")

    plan = plan_queue(
        [tmp_path / "Show.Name.S01E01.mkv"], _options(CollisionPolicy.SKIP), _show_name()
    ).plan

    [entry] = plan.entries
    assert (entry.destination, entry.status) == (None, EntryStatus.NAME_TAKEN)
