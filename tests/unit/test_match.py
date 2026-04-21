"""Tests for metadata fetch helpers."""

from __future__ import annotations

import pytest

from termrenamer.api.tmdb import StaticFilmMetadataProvider
from termrenamer.core.match import fetch_film_metadata
from termrenamer.core.models import FilmParseResult, MovieMetadata
from termrenamer.util.errors import ProviderError


def test_fetch_film_retries_without_year() -> None:
    provider = StaticFilmMetadataProvider(
        _mapping={
            ("foo", None): MovieMetadata(title="Foo", year=2020),
        },
    )
    parsed = FilmParseResult(title_hint="foo", year_hint=2026)
    meta = fetch_film_metadata(provider, parsed)
    assert meta.title == "Foo"


def test_fetch_film_no_year_both_fail() -> None:
    provider = StaticFilmMetadataProvider(_mapping={})
    parsed = FilmParseResult(title_hint="nope", year_hint=2026)
    with pytest.raises(ProviderError):
        fetch_film_metadata(provider, parsed)
