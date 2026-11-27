"""Integration tests for apply."""

from __future__ import annotations

from pathlib import Path

from conftest import plan_folder
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, ScanMode


def test_apply_creates_destination_tree(tmp_path: Path) -> None:
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"x")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    results = apply_plan(plan, confirmed=True)
    assert all(r.status is ApplyStatus.RENAMED for r in results)
    assert (tmp_path / "Show" / "Season 01").is_dir()
