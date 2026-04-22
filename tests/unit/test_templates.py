"""Tests for default destination templates."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import EpisodeMetadata, MovieMetadata, ParseResult
from termrenamer.core.templates import format_film_destination, format_tv_destination


def test_format_film_destination_no_dest_root(tmp_path: Path) -> None:
    root = tmp_path / "in"
    meta = MovieMetadata(title="Hoppers", year=2026)
    orig = root / "Hoppers (2026)" / "file.mkv"
    p = format_film_destination(root=root, metadata=meta, original_path=orig)
    assert p == root / "Hoppers (2026)" / "Hoppers (2026).mkv"


def test_format_film_destination_with_dest_root(tmp_path: Path) -> None:
    root = tmp_path / "in"
    dest_root = tmp_path / "out"
    meta = MovieMetadata(title="Hoppers", year=2026)
    orig = root / "Hoppers (2026)" / "file.mkv"
    p = format_film_destination(
        root=root,
        metadata=meta,
        original_path=orig,
        dest_root=dest_root,
    )
    assert p == dest_root / "Hoppers (2026)" / "Hoppers (2026).mkv"


def test_format_tv_destination_no_dest_root(tmp_path: Path) -> None:
    root = tmp_path / "in"
    pr = ParseResult(show_hint="S", season=1, episodes=(1,))
    meta = EpisodeMetadata(show_title="Show", episode_title="Pilot")
    orig = root / "S01E01.mkv"
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
    )
    assert p.parent == root / "Show" / "Season 01"


def test_format_tv_destination_with_dest_root(tmp_path: Path) -> None:
    root = tmp_path / "in"
    dest_root = tmp_path / "tv_out"
    pr = ParseResult(show_hint="S", season=1, episodes=(1,))
    meta = EpisodeMetadata(show_title="Show", episode_title="Pilot")
    orig = root / "S01E01.mkv"
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
        dest_root=dest_root,
    )
    assert p.parent == dest_root / "Show" / "Season 01"


def test_tv_in_place_ignores_dest_root(
    tmp_path: Path,
) -> None:
    """Folder rename off: only filename under source parent; no destination root."""
    root = tmp_path / "tv_stuff"
    season1 = root / "The Simpsons" / "Season1"
    season1.mkdir(parents=True)
    orig = season1 / "S01E02 - something something.mkv"
    pr = ParseResult(show_hint="S", season=1, episodes=(2,))
    meta = EpisodeMetadata(show_title="The Simpsons", episode_title="Bart the Hero")
    dest_root = tmp_path / "destination_folder"
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
        dest_root=dest_root,
        enable_folder_rename=False,
        enable_season_folders=True,
    )
    assert p.parent == season1
    assert p.suffix == ".mkv"
    assert "The Simpsons" in p.name
    assert "S01E02" in p.name


def test_tv_flat_under_show_no_season_folder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tv_stuff"
    season1 = root / "The Simpsons" / "Season1"
    season1.mkdir(parents=True)
    orig = season1 / "S01E02 - something something.mkv"
    pr = ParseResult(show_hint="S", season=1, episodes=(2,))
    meta = EpisodeMetadata(show_title="The Simpsons", episode_title="Bart the Hero")
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
        enable_folder_rename=True,
        enable_season_folders=False,
    )
    assert p.parent == root / "The Simpsons"


def test_tv_season_subfolder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tv_stuff"
    season1 = root / "The Simpsons" / "Season1"
    season1.mkdir(parents=True)
    orig = season1 / "S01E02 - something something.mkv"
    pr = ParseResult(show_hint="S", season=1, episodes=(2,))
    meta = EpisodeMetadata(show_title="The Simpsons", episode_title="Bart the Hero")
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
        enable_folder_rename=True,
        enable_season_folders=True,
    )
    assert p.parent == root / "The Simpsons" / "Season 01"


def test_tv_dest_root_season_folders(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "destination_folder"
    root = tmp_path / "tv_stuff"
    season1 = root / "The Simpsons" / "Season1"
    season1.mkdir(parents=True)
    orig = season1 / "S01E02 - something something.mkv"
    pr = ParseResult(show_hint="S", season=1, episodes=(2,))
    meta = EpisodeMetadata(show_title="The Simpsons", episode_title="Bart the Hero")
    p = format_tv_destination(
        root=root,
        parse=pr,
        metadata=meta,
        original_path=orig,
        dest_root=dest_root,
        enable_folder_rename=True,
        enable_season_folders=True,
    )
    assert p.parent == dest_root / "The Simpsons" / "Season 01"


def test_film_in_place_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "in"
    folder = root / "Some (1999)" / "nested"
    folder.mkdir(parents=True)
    orig = folder / "old.mkv"
    meta = MovieMetadata(title="Hoppers", year=2026)
    dest = tmp_path / "out"
    p = format_film_destination(
        root=root,
        metadata=meta,
        original_path=orig,
        dest_root=dest,
        enable_folder_rename=False,
    )
    assert p.parent == folder
    assert p.name == "Hoppers (2026).mkv"


def test_film_with_dest_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "in"
    dest_root = tmp_path / "destination_folder"
    orig = root / "file.mkv"
    orig.parent.mkdir(parents=True)
    meta = MovieMetadata(title="Hoppers", year=2026)
    p = format_film_destination(
        root=root,
        metadata=meta,
        original_path=orig,
        dest_root=dest_root,
        enable_folder_rename=True,
    )
    assert p == dest_root / "Hoppers (2026)" / "Hoppers (2026).mkv"
