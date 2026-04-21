"""End-to-end pipeline with stub provider (no network)."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan


def test_full_pipeline_stub(tmp_path: Path) -> None:
    root = tmp_path
    (root / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (root / "Show.Name.S01E01.srt").write_text("sub", encoding="utf-8")
    (root / "Show.Name.S01E02.mkv").write_bytes(b"b")
    (root / "Another.Show.S02E05.WEB.mp4").write_bytes(b"c")
    (root / "random_notes.txt").write_text("notes", encoding="utf-8")

    mapping = {
        ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        ("show name", 1, 2): EpisodeMetadata(show_title="Show Name", episode_title="The Second"),
        ("another show", 2, 5): EpisodeMetadata(
            show_title="Another Show", episode_title="Midpoint"
        ),
    }
    provider = StaticTvMetadataProvider(_mapping=mapping)

    plan = build_rename_plan(root=root, mode=ScanMode.TV, provider=provider)
    assert len(plan.entries) == 4

    results = apply_plan(plan, confirmed=True)
    assert all(r.status is ApplyStatus.SUCCESS for r in results)
    assert (root / "random_notes.txt").exists()
    remaining = {p.name for p in root.rglob("*") if p.is_file()}
    assert "random_notes.txt" in remaining


def test_tv_dest_root_pipeline(tmp_path: Path) -> None:
    root = tmp_path / "in"
    tv_dest = tmp_path / "tv_out"
    root.mkdir()
    (root / "Show.Name.S01E01.mkv").write_bytes(b"a")
    mapping = {
        ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
    }
    provider = StaticTvMetadataProvider(_mapping=mapping)
    plan = build_rename_plan(
        root=root,
        mode=ScanMode.TV,
        provider=provider,
        tv_dest_root=tv_dest,
    )
    results = apply_plan(plan, confirmed=True)
    assert all(r.status is ApplyStatus.SUCCESS for r in results)
    assert (tv_dest / "Show Name" / "Season 01").exists()
