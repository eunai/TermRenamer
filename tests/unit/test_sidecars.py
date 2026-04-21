"""Tests for sidecar grouping."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan
from termrenamer.core.scan import scan
from termrenamer.core.sidecars import find_primary_for_sidecar, partition_by_kind


def test_find_primary_matches_stem_and_parent(tmp_path: Path) -> None:
    root = tmp_path
    (root / "foo.mkv").write_bytes(b"v")
    (root / "foo.srt").write_text("s", encoding="utf-8")
    (root / "bar.mp4").write_bytes(b"v")

    files = scan(root=root)
    videos, sidecars = partition_by_kind(files)
    assert len(videos) == 2
    assert len(sidecars) == 1
    primary = find_primary_for_sidecar(sidecars[0], videos)
    assert primary is not None
    assert primary.path.name == "foo.mkv"


def test_sidecar_matches_primary_destination_stem(tmp_path: Path) -> None:
    """Sidecar destination stem matches primary (same template base)."""
    root = tmp_path
    (root / "Vid.S01E01.mkv").write_bytes(b"v")
    (root / "Vid.S01E01.srt").write_text("s", encoding="utf-8")

    provider = StaticTvMetadataProvider(
        _mapping={
            ("vid", 1, 1): EpisodeMetadata(show_title="X Show", episode_title="Pilot"),
        },
    )
    plan = build_rename_plan(root=root, mode=ScanMode.TV, provider=provider)
    primary = next(e for e in plan.entries if e.source.suffix == ".mkv")
    sidecar = next(e for e in plan.entries if e.source.suffix == ".srt")
    assert primary.destination.stem == sidecar.destination.stem
