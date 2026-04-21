"""Planning wiring: provider selection and validation."""

from __future__ import annotations

import pytest

from termrenamer.api.omdb import StaticOmdbFilmMetadataProvider
from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.util.errors import ValidationError
from termrenamer.wiring import PlanningWiring


def test_resolve_tv_tmdb() -> None:
    tv = StaticTvMetadataProvider(
        _mapping={("x", 1, 1): EpisodeMetadata(show_title="X", episode_title="Pilot")},
    )
    film = StaticFilmMetadataProvider(_mapping={("m", 2020): MovieMetadata(title="M", year=2020)})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    assert w.resolve_tv(provider_id="tmdb") is tv


def test_resolve_tv_tvdb_missing_raises() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    with pytest.raises(ValidationError, match="TheTVDB requires"):
        w.resolve_tv(provider_id="tvdb")


def test_resolve_tv_tvdb_ok() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    tvdb = StaticTvMetadataProvider(
        _mapping={("y", 2, 2): EpisodeMetadata(show_title="Y", episode_title="E")},
    )
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=tvdb, film=film, film_omdb=None)
    assert w.resolve_tv(provider_id="tvdb") is tvdb


def test_resolve_tv_unknown_provider() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    with pytest.raises(ValidationError, match="Unknown TV provider"):
        w.resolve_tv(provider_id="other")


def test_resolve_film_tmdb() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    assert w.resolve_film(provider_id="tmdb") is film


def test_resolve_film_omdb_missing_raises() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    with pytest.raises(ValidationError, match="OMDb requires"):
        w.resolve_film(provider_id="omdb")


def test_resolve_film_omdb_ok() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    omdb = StaticOmdbFilmMetadataProvider(
        _mapping={("m", 2020): MovieMetadata(title="M", year=2020)},
    )
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=omdb)
    assert w.resolve_film(provider_id="omdb") is omdb


def test_resolve_film_unknown_provider() -> None:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    w = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    with pytest.raises(ValidationError, match="Unknown film provider"):
        w.resolve_film(provider_id="other")
