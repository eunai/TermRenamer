"""Tests for the metadata fetch helpers over the Provider seam."""

from __future__ import annotations

import pytest

from termrenamer.api.lookup import FilmLookup
from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.match import fetch_episode_metadata, fetch_film_metadata
from termrenamer.core.models import (
    Candidate,
    EpisodeMetadata,
    FilmParseResult,
    MovieMetadata,
    ParseResult,
)
from termrenamer.util.errors import ProviderError


def test_fetch_film_through_a_lookup_retries_without_year() -> None:
    provider = StaticFilmMetadataProvider(
        _mapping={("foo", None): MovieMetadata(title="Foo", year=2020)},
    )
    parsed = FilmParseResult(title_hint="foo", year_hint=2026)
    assert fetch_film_metadata(FilmLookup(provider), parsed) == MovieMetadata(
        title="Foo", year=2020
    )


def test_fetch_film_found_neither_way_is_nothing_found() -> None:
    provider = StaticFilmMetadataProvider(_mapping={})
    parsed = FilmParseResult(title_hint="nope", year_hint=2026)
    assert fetch_film_metadata(FilmLookup(provider), parsed) is None


def test_fetch_film_takes_the_first_result() -> None:
    class TwoFilms:
        def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
            return (
                Candidate(id="1", name="First", year=2001),
                Candidate(id="2", name="Second", year=2002),
            )

    parsed = FilmParseResult(title_hint="x", year_hint=None)
    assert fetch_film_metadata(TwoFilms(), parsed) == MovieMetadata(title="First", year=2001)


def test_fetch_film_result_without_a_year_is_a_failure() -> None:
    class NoYear:
        def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
            return (Candidate(id="1", name="First", year=None),)

    with pytest.raises(ProviderError, match="release year"):
        fetch_film_metadata(NoYear(), FilmParseResult(title_hint="x", year_hint=None))


def test_fetch_episode_uses_the_first_show_found() -> None:
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 2): EpisodeMetadata(show_title="Show", episode_title="Two")},
    )
    parsed = ParseResult(show_hint="Show", season=1, episodes=(2, 3))
    assert fetch_episode_metadata(provider, parsed) == EpisodeMetadata(
        show_title="Show", episode_title="Two"
    )


def test_fetch_episode_nothing_found() -> None:
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 2): EpisodeMetadata(show_title="Show", episode_title="Two")},
    )
    assert fetch_episode_metadata(provider, ParseResult("Other", 1, (2,))) is None
    assert fetch_episode_metadata(provider, ParseResult("Show", 9, (9,))) is None
