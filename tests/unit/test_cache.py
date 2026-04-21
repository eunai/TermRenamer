"""SQLite metadata cache unit tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from termrenamer.api.caching import CachedTvMetadataProvider
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import CacheError


def test_tv_cache_miss_and_put_round_trip(tmp_path) -> None:
    path = tmp_path / "cache.db"
    cache = SqliteMetadataCache(path)
    assert cache.get_tv_episode(show_hint="Show", season=1, episode=1) is None
    meta = EpisodeMetadata(show_title="Show", episode_title="Pilot")
    cache.put_tv_episode(show_hint="Show", season=1, episode=1, metadata=meta)
    got = cache.get_tv_episode(show_hint="Show", season=1, episode=1)
    assert got == meta
    cache.close()


def test_film_cache_round_trip(tmp_path) -> None:
    path = tmp_path / "c.db"
    cache = SqliteMetadataCache(path)
    from termrenamer.core.models import MovieMetadata

    m = MovieMetadata(title="Film", year=2020)
    cache.put_film(title_hint="film", year_hint=2020, metadata=m)
    assert cache.get_film(title_hint="film", year_hint=2020) == m
    cache.put_film(title_hint="film", year_hint=None, metadata=m)
    assert cache.get_film(title_hint="film", year_hint=None) == m
    cache.close()


def test_cached_tv_provider_degrades_on_cache_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    path = tmp_path / "c.db"
    cache = SqliteMetadataCache(path)
    meta_in = EpisodeMetadata(show_title="S", episode_title="E")
    inner = StaticTvMetadataProvider(
        _mapping={("x", 1, 1): meta_in},
    )
    wrapped = CachedTvMetadataProvider(inner, cache)

    def _boom(
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata | None:
        raise CacheError("cache read failed")

    monkeypatch.setattr(cache, "get_tv_episode", _boom)
    meta = wrapped.resolve_tv_episode(show_hint="x", season=1, episode=1)
    assert meta == meta_in
    assert "cache" in caplog.text.lower()


def test_corrupt_db_raises_cache_error(tmp_path) -> None:
    p = tmp_path / "bad.db"
    p.write_bytes(b"CORRUPT")
    cache = SqliteMetadataCache(p)
    with pytest.raises(CacheError):
        cache.get_tv_episode(show_hint="a", season=1, episode=1)
