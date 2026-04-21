"""Apply engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyStatus,
    EpisodeMetadata,
    PlanEntryStatus,
    PlanFingerprint,
    RenamePlan,
    RenamePlanEntry,
    ScanMode,
)
from termrenamer.core.planning import build_rename_plan
from termrenamer.util.errors import ValidationError


def test_apply_requires_confirmation(tmp_path: Path) -> None:
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"v")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="S", episode_title="E")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    with pytest.raises(ValidationError):
        apply_plan(plan, confirmed=False)


def test_apply_moves_files(tmp_path: Path) -> None:
    vid = tmp_path / "Show.S01E01.mkv"
    vid.write_bytes(b"data")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    results = apply_plan(plan, confirmed=True)
    assert all(r.status is ApplyStatus.SUCCESS for r in results)
    assert not vid.exists()
    assert any(p.exists() for p in tmp_path.rglob("*.mkv"))


def test_apply_skips_stale_source(tmp_path: Path) -> None:
    vid = tmp_path / "Show.S01E01.mkv"
    vid.write_bytes(b"data")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    vid.unlink()
    results = apply_plan(plan, confirmed=True)
    assert results[0].status is ApplyStatus.SKIP


def test_apply_operation_order_lexical(tmp_path: Path) -> None:
    (tmp_path / "b.S01E01.mkv").write_bytes(b"b")
    (tmp_path / "a.S01E01.mkv").write_bytes(b"a")
    provider = StaticTvMetadataProvider(
        _mapping={
            ("b", 1, 1): EpisodeMetadata(show_title="B", episode_title="E"),
            ("a", 1, 1): EpisodeMetadata(show_title="A", episode_title="E"),
        },
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    assert [e.source.name for e in plan.entries] == ["a.S01E01.mkv", "b.S01E01.mkv"]


def test_apply_skips_unmatched_entry(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x")
    st = src.stat()
    fp = PlanFingerprint(path=src, size=st.st_size, mtime_ns=int(st.st_mtime_ns))
    entry = RenamePlanEntry(
        source=src,
        destination=tmp_path / "Movie not found.",
        root=root,
        is_primary=True,
        primary_source=None,
        fingerprint=fp,
        group_id="g",
        status=PlanEntryStatus.UNMATCHED,
    )
    plan = RenamePlan(entries=(entry,), mode=ScanMode.FILM)
    results = apply_plan(plan, confirmed=True)
    assert len(results) == 1
    assert results[0].status is ApplyStatus.SKIP
    assert "unmatched" in results[0].reason
    assert src.exists()


def test_remove_empty_source_dirs_skips_non_empty(tmp_path: Path) -> None:
    from termrenamer.core.apply import _remove_empty_source_dirs

    d = tmp_path / "keep"
    d.mkdir()
    (d / "file.txt").write_text("x", encoding="utf-8")
    _remove_empty_source_dirs({d})
    assert d.is_dir()
    assert (d / "file.txt").exists()


def test_remove_empty_source_dirs_deepest_first(tmp_path: Path) -> None:
    from termrenamer.core.apply import _remove_empty_source_dirs

    deep = tmp_path / "x" / "y" / "z"
    deep.mkdir(parents=True)
    parents = {tmp_path / "x" / "y" / "z", tmp_path / "x" / "y", tmp_path / "x"}
    _remove_empty_source_dirs(parents)
    assert not (tmp_path / "x").exists()
