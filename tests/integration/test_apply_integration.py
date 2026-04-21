"""Integration tests for apply."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan


def test_apply_creates_destination_tree(tmp_path: Path) -> None:
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"x")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    results = apply_plan(plan, confirmed=True)
    assert all(r.status is ApplyStatus.SUCCESS for r in results)
    assert (tmp_path / "Show" / "Season 01").is_dir()
