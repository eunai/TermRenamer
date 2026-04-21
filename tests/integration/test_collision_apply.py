"""Collision behavior at apply time."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan


def test_apply_skips_when_destination_appeared(tmp_path: Path) -> None:
    src = tmp_path / "Show.S01E01.mkv"
    src.write_bytes(b"data")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    dest = next(e.destination for e in plan.entries)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"blocker")

    results = apply_plan(plan, confirmed=True)
    assert any(r.status is ApplyStatus.SKIP for r in results)
