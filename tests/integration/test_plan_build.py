"""Integration: scan to plan with stub provider."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan


def test_scan_to_plan(tmp_path: Path) -> None:
    (tmp_path / "X.S01E01.mkv").write_bytes(b"1")
    provider = StaticTvMetadataProvider(
        _mapping={("x", 1, 1): EpisodeMetadata(show_title="X", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    assert len(plan.entries) == 1
