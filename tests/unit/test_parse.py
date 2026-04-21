"""Tests for TV filename parsing."""

from __future__ import annotations

import pytest

from termrenamer.core.models import ScanMode
from termrenamer.core.parse import parse_filename, parse_film_filename
from termrenamer.util.errors import ParseError


@pytest.mark.parametrize(
    ("filename", "show", "season", "episodes"),
    [
        ("Show.Name.S01E01.720p.BluRay.mkv", "Show Name", 1, (1,)),
        ("show.name.s02e03.hdtv.mp4", "show name", 2, (3,)),
        ("Show_Name_S01E01E02_1080p.mkv", "Show Name", 1, (1, 2)),
    ],
)
def test_parse_good(filename: str, show: str, season: int, episodes: tuple[int, ...]) -> None:
    result = parse_filename(name=filename, mode=ScanMode.TV)
    assert result.show_hint == show
    assert result.season == season
    assert result.episodes == episodes


@pytest.mark.parametrize("filename", ["random_file.mkv", "notes.txt"])
def test_parse_bad(filename: str) -> None:
    with pytest.raises(ParseError):
        parse_filename(name=filename, mode=ScanMode.TV)


def test_daily_without_season_ep_raises() -> None:
    with pytest.raises(ParseError):
        parse_filename(name="Show.Name.2024.01.15.WEB.mkv", mode=ScanMode.TV)


def test_parse_film_with_year() -> None:
    r = parse_film_filename(name="The.Matrix.1999.1080p.BluRay.mkv")
    assert r.title_hint == "The Matrix"
    assert r.year_hint == 1999


def test_parse_film_no_year() -> None:
    r = parse_film_filename(name="Some.Indie.Film.1080p.mkv")
    assert r.title_hint == "Some Indie Film"
    assert r.year_hint is None


def test_parse_film_parenthesized_year() -> None:
    r = parse_film_filename(name="Starbright (2026).mkv")
    assert r.title_hint == "Starbright"
    assert r.year_hint == 2026


def test_parse_film_parenthesized_year_with_tags() -> None:
    r = parse_film_filename(
        name="The Red Balloon (1956) (1080p BluRay x265 Foo).mkv",
    )
    assert r.title_hint == "The Red Balloon"
    assert r.year_hint == 1956
