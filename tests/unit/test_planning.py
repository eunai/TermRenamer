"""Tests for rename plan construction."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata, PlanEntryStatus, ScanMode
from termrenamer.core.planning import (
    build_rename_plan,
    filter_plan_to_queued_path,
    merge_rename_plans,
)


def test_plan_groups_sidecar_with_primary(tmp_path: Path) -> None:
    root = tmp_path
    (root / "ShowA.S01E01.mkv").write_bytes(b"v")
    (root / "ShowA.S01E01.srt").write_text("x", encoding="utf-8")

    provider = StaticTvMetadataProvider(
        _mapping={
            ("showa", 1, 1): EpisodeMetadata(show_title="Show A", episode_title="Pilot"),
        },
    )
    plan = build_rename_plan(root=root, mode=ScanMode.TV, provider=provider)
    assert len(plan.entries) == 2
    dests = {e.source.name: e.destination for e in plan.entries}
    assert dests["ShowA.S01E01.srt"].name.startswith("Show A - S01E01 - Pilot")
    assert dests["ShowA.S01E01.srt"].suffix == ".srt"


def test_plan_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path
    (root / "z_show.S01E01.mkv").write_bytes(b"1")
    (root / "a_show.S01E01.mkv").write_bytes(b"2")

    provider = StaticTvMetadataProvider(
        _mapping={
            ("z show", 1, 1): EpisodeMetadata(show_title="Z", episode_title="E"),
            ("a show", 1, 1): EpisodeMetadata(show_title="A", episode_title="E"),
        },
    )
    p1 = build_rename_plan(root=root, mode=ScanMode.TV, provider=provider)
    p2 = build_rename_plan(root=root, mode=ScanMode.TV, provider=provider)
    assert [e.source for e in p1.entries] == [e.source for e in p2.entries]


def test_film_plan_unmatched_continues(tmp_path: Path) -> None:
    (tmp_path / "Good.1999.mkv").write_bytes(b"a")
    (tmp_path / "Bad.1080p.mkv").write_bytes(b"b")
    provider = StaticFilmMetadataProvider(
        _mapping={
            ("good", 1999): MovieMetadata(title="Good", year=1999),
        },
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.FILM, provider=provider)
    assert len(plan.entries) == 2
    by_name = {e.source.name: e for e in plan.entries}
    assert by_name["Good.1999.mkv"].status is PlanEntryStatus.MATCHED
    assert by_name["Bad.1080p.mkv"].status is PlanEntryStatus.UNMATCHED
    assert "Movie not found." in str(by_name["Bad.1080p.mkv"].destination)


def test_tv_plan_unmatched_entry(tmp_path: Path) -> None:
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"v")
    provider = StaticTvMetadataProvider(_mapping={})
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    assert len(plan.entries) == 1
    e = plan.entries[0]
    assert e.status is PlanEntryStatus.UNMATCHED
    assert "Episode not found." in str(e.destination)


def test_filter_plan_to_queued_path_keeps_only_target_video(tmp_path: Path) -> None:
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="A"),
            ("show name", 1, 2): EpisodeMetadata(show_title="Show Name", episode_title="B"),
        },
    )
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E02.mkv").write_bytes(b"b")
    full = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    assert len(full.entries) == 2
    picked = tmp_path / "Show.Name.S01E01.mkv"
    narrow = filter_plan_to_queued_path(full, picked)
    assert len(narrow.entries) == 1
    assert narrow.entries[0].source == picked


def test_merge_rename_plans_combines_two_roots(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )
    (a / "Show.Name.S01E01.mkv").write_bytes(b"x")
    (b / "Show.Name.S01E01.mkv").write_bytes(b"y")
    p1 = build_rename_plan(root=a, mode=ScanMode.TV, provider=provider)
    p2 = build_rename_plan(root=b, mode=ScanMode.TV, provider=provider)
    merged = merge_rename_plans((p1, p2))
    assert len(merged.entries) == 2


def test_plan_ignores_tv_dest_when_folder_rename_off(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"x")
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(
                show_title="Show Name",
                episode_title="Pilot",
            ),
        },
    )
    dest = tmp_path / "separate_out"
    dest.mkdir()
    plan = build_rename_plan(
        root=tmp_path,
        mode=ScanMode.TV,
        provider=provider,
        tv_dest_root=dest,
        enable_folder_rename=False,
        enable_season_folders=False,
    )
    assert len(plan.entries) == 1
    assert plan.entries[0].destination.parent == tmp_path


def test_merge_rename_plans_suffixes_when_destinations_collide(tmp_path: Path) -> None:
    """Two identical relative layouts can map to the same library leaf name."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )
    (a / "Show.Name.S01E01.mkv").write_bytes(b"x")
    (b / "Show.Name.S01E01.mkv").write_bytes(b"y")
    tv_dest = tmp_path / "out"
    tv_dest.mkdir()
    p1 = build_rename_plan(
        root=a,
        mode=ScanMode.TV,
        provider=provider,
        tv_dest_root=tv_dest,
    )
    p2 = build_rename_plan(
        root=b,
        mode=ScanMode.TV,
        provider=provider,
        tv_dest_root=tv_dest,
    )
    merged = merge_rename_plans((p1, p2))
    dest_names = [e.destination.name for e in merged.entries]
    assert len(dest_names) == 2
    assert any(n.endswith(".mkv") for n in dest_names)
    assert len(set(dest_names)) == 2
