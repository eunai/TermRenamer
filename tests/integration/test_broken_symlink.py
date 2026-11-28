"""A broken symbolic link at a wanted name counts as taken (#9, #17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import plan_folder
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, Plan, ScanMode


def _can_symlink(base: Path) -> bool:
    probe = base / ".symlink-probe"
    try:
        probe.symlink_to(base / ".symlink-probe-target")
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


@pytest.fixture
def media(tmp_path: Path) -> Path:
    if not _can_symlink(tmp_path):
        pytest.skip("this system cannot create symbolic links")
    return tmp_path


def _plant_broken_link(at: Path) -> None:
    at.parent.mkdir(parents=True, exist_ok=True)
    at.symlink_to(at.parent / "missing-target")
    assert at.is_symlink()
    assert not at.exists()


def _pilot_provider() -> StaticTvMetadataProvider:
    return StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )


def _plan(root: Path, **kwargs: bool) -> Plan:
    return plan_folder(root, ScanMode.TV, _pilot_provider(), **kwargs)


def _planned_for(plan: Plan, source_name: str) -> Path:
    return next(e.destination for e in plan.entries if e.source.name == source_name)


def test_apply_skips_entry_when_broken_link_appears_at_destination(media: Path) -> None:
    src = media / "Show.S01E01.mkv"
    src.write_bytes(b"data")
    plan = _plan(media)
    dest = plan.entries[0].destination
    _plant_broken_link(dest)

    results = apply_plan(plan, confirmed=True).results

    assert [(r.status, r.reason) for r in results] == [
        (ApplyStatus.SKIP, "destination exists at apply time"),
    ]
    assert src.read_bytes() == b"data"
    assert dest.is_symlink()
    assert not dest.exists()


def test_plan_numbers_an_entry_whose_wanted_name_is_a_broken_link(media: Path) -> None:
    (media / "Show.S01E01.mkv").write_bytes(b"data")
    wanted = _plan(media).entries[0].destination
    _plant_broken_link(wanted)

    planned = _planned_for(_plan(media), "Show.S01E01.mkv")

    assert planned == wanted.with_name("Show - S01E01 - Pilot (1).mkv")


def _straggler_backups(media: Path) -> Path:
    season = media / "in" / "The Show" / "Season1"
    season.mkdir(parents=True)
    (season / "Show.S01E01.mkv").write_bytes(b"v")
    (season / "extra.nfo").write_text("nfo", encoding="utf-8")
    return season


def test_straggler_whose_name_is_a_broken_link_gets_the_numbered_name(media: Path) -> None:
    season = _straggler_backups(media)
    first = _plan(media / "in", folder_rename=True, season_folders=True)
    dest_folder = first.entries[0].destination.parent
    _plant_broken_link(dest_folder / "extra.nfo")

    plan = _plan(media / "in", folder_rename=True, season_folders=True)
    outcome = apply_plan(plan, confirmed=True)

    assert [s.destination for s in plan.stragglers] == [dest_folder / "extra (1).nfo"]
    assert [r.status for r in outcome.results] == [ApplyStatus.RENAMED]
    assert (dest_folder / "extra (1).nfo").read_text(encoding="utf-8") == "nfo"
    assert (dest_folder / "extra.nfo").is_symlink()
    assert not (season / "extra.nfo").exists()


def test_straggler_skipped_when_broken_link_appears_at_its_path(media: Path) -> None:
    season = _straggler_backups(media)
    plan = _plan(media / "in", folder_rename=True, season_folders=True)
    [straggler] = plan.stragglers
    _plant_broken_link(straggler.destination)

    outcome = apply_plan(plan, confirmed=True)

    assert [(r.status, r.reason) for r in outcome.stragglers] == [
        (ApplyStatus.SKIP, "destination exists at apply time"),
    ]
    assert (season / "extra.nfo").read_text(encoding="utf-8") == "nfo"
    assert straggler.destination.is_symlink()


def test_apply_skips_entry_when_link_to_an_existing_file_appears_at_destination(
    media: Path,
) -> None:
    src = media / "Show.S01E01.mkv"
    src.write_bytes(b"data")
    other = media / "other.bin"
    other.write_bytes(b"other")
    plan = _plan(media)
    dest = plan.entries[0].destination
    dest.parent.mkdir(parents=True)
    dest.symlink_to(other)

    results = apply_plan(plan, confirmed=True).results

    assert [(r.status, r.reason) for r in results] == [
        (ApplyStatus.SKIP, "destination exists at apply time"),
    ]
    assert src.read_bytes() == b"data"
    assert other.read_bytes() == b"other"


def test_plan_numbers_an_entry_whose_wanted_name_links_to_an_existing_file(
    media: Path,
) -> None:
    (media / "Show.S01E01.mkv").write_bytes(b"data")
    other = media / "other.bin"
    other.write_bytes(b"other")
    wanted = _plan(media).entries[0].destination
    wanted.parent.mkdir(parents=True)
    wanted.symlink_to(other)

    planned = _planned_for(_plan(media), "Show.S01E01.mkv")

    assert planned == wanted.with_name("Show - S01E01 - Pilot (1).mkv")


def test_case_only_rename_keeps_the_wanted_name_and_applies(tmp_path: Path) -> None:
    folder = tmp_path / "Show" / "Season 01"
    folder.mkdir(parents=True)
    src = folder / "show - s01e01 - pilot.mkv"
    src.write_bytes(b"data")
    plan = _plan(tmp_path)
    dest = plan.entries[0].destination
    assert dest == folder / "Show - S01E01 - Pilot.mkv"

    results = apply_plan(plan, confirmed=True).results

    assert [r.status for r in results] == [ApplyStatus.RENAMED]
    assert [p.name for p in folder.iterdir()] == ["Show - S01E01 - Pilot.mkv"]
