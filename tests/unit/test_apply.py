"""Apply engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import plan_folder
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import ApplyStatus, EpisodeMetadata, ScanMode
from termrenamer.util.errors import ValidationError


def test_apply_requires_confirmation(tmp_path: Path) -> None:
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"v")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="S", episode_title="E")},
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    with pytest.raises(ValidationError):
        apply_plan(plan, confirmed=False)


def test_apply_moves_files(tmp_path: Path) -> None:
    vid = tmp_path / "Show.S01E01.mkv"
    vid.write_bytes(b"data")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    results = apply_plan(plan, confirmed=True).results
    assert all(r.status is ApplyStatus.RENAMED for r in results)
    assert not vid.exists()
    assert any(p.exists() for p in tmp_path.rglob("*.mkv"))


def test_apply_skips_stale_source(tmp_path: Path) -> None:
    vid = tmp_path / "Show.S01E01.mkv"
    vid.write_bytes(b"data")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    vid.unlink()
    results = apply_plan(plan, confirmed=True).results
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
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    assert [e.source.name for e in plan.entries] == ["a.S01E01.mkv", "b.S01E01.mkv"]


def test_remove_empty_source_dirs_skips_non_empty(tmp_path: Path) -> None:
    from termrenamer.core.apply import _remove_empty_source_dirs
    from termrenamer.core.moving import Changes

    d = tmp_path / "keep"
    d.mkdir()
    (d / "file.txt").write_text("x", encoding="utf-8")
    _remove_empty_source_dirs({d}, Changes())
    assert d.is_dir()
    assert (d / "file.txt").exists()


def test_apply_merge_stragglers_moves_extra_files_to_dest_parent(
    tmp_path: Path,
) -> None:
    """With Folder rename on, files left in the source folder move with collision rules."""
    base = tmp_path / "in" / "The Simpsons" / "Season1"
    base.mkdir(parents=True)
    vid = base / "Show.Name.S01E01.mkv"
    vid.write_bytes(b"v")
    (base / "extra.nfo").write_text("nfo", encoding="utf-8")
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(
                show_title="Show Name",
                episode_title="Pilot",
            ),
        },
    )
    plan = plan_folder(
        tmp_path / "in",
        ScanMode.TV,
        provider,
        folder_rename=True,
        season_folders=True,
    )
    assert len(plan.entries) == 1
    main_dest = plan.entries[0].destination
    results = apply_plan(plan, confirmed=True).results
    assert [r.status for r in results] == [ApplyStatus.RENAMED]
    nfo_gone = (base / "extra.nfo").exists()
    assert not nfo_gone
    nfo_at_dest = main_dest.parent / "extra.nfo"
    assert nfo_at_dest.is_file()
    assert nfo_at_dest.read_text(encoding="utf-8") == "nfo"


def test_remove_empty_source_dirs_deepest_first(tmp_path: Path) -> None:
    from termrenamer.core.apply import _remove_empty_source_dirs
    from termrenamer.core.moving import Changes

    deep = tmp_path / "x" / "y" / "z"
    deep.mkdir(parents=True)
    parents = {tmp_path / "x" / "y" / "z", tmp_path / "x" / "y", tmp_path / "x"}
    _remove_empty_source_dirs(parents, Changes())
    assert not (tmp_path / "x").exists()
