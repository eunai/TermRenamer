"""Integration tests for sidecar grouping in plans."""

from __future__ import annotations

from pathlib import Path

from conftest import plan_folder
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, ScanMode


def test_sidecar_moves_with_primary(tmp_path: Path) -> None:
    (tmp_path / "foo.S01E01.mkv").write_bytes(b"v")
    (tmp_path / "foo.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "bar.S01E01.mp4").write_bytes(b"v")

    provider = StaticTvMetadataProvider(
        _mapping={
            ("foo", 1, 1): EpisodeMetadata(show_title="Foo", episode_title="Ep"),
            ("bar", 1, 1): EpisodeMetadata(show_title="Bar", episode_title="Ep"),
        },
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    names = {e.source.name for e in plan.entries}
    assert "foo.S01E01.srt" in names
    prim = next(e for e in plan.entries if e.source.name == "foo.S01E01.mkv")
    side = next(e for e in plan.entries if e.source.name == "foo.S01E01.srt")
    assert side.video == prim.source
    assert prim.destination.stem.split()[0] == side.destination.stem.split()[0]
