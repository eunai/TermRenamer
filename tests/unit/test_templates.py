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
