"""Cache-wrapped metadata providers (uses ``persistence/`` SQLite only for storage)."""

from __future__ import annotations

import logging

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import CacheError

_LOG = logging.getLogger(__name__)


class CachedTvMetadataProvider:
    """Delegate to a TV provider; read-through / write-through SQLite cache."""

    def __init__(self, inner: TvMetadataProvider, cache: SqliteMetadataCache) -> None:
        self._inner = inner
        self._cache = cache

    def resolve_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata:
        try:
            hit = self._cache.get_tv_episode(
                show_hint=show_hint,
                season=season,
                episode=episode,
            )
        except CacheError as exc:
            _LOG.warning("TV cache read failed; using network: %s", exc)
            hit = None
        if hit is not None:
            return hit
        meta = self._inner.resolve_tv_episode(
            show_hint=show_hint,
            season=season,
            episode=episode,
        )
        try:
            self._cache.put_tv_episode(
                show_hint=show_hint,
                season=season,
                episode=episode,
                metadata=meta,
            )
        except CacheError as exc:
            _LOG.warning("TV cache write failed (ignored): %s", exc)
        return meta


class CachedFilmMetadataProvider:
    """Delegate to a film provider; read-through / write-through SQLite cache."""

    def __init__(self, inner: FilmMetadataProvider, cache: SqliteMetadataCache) -> None:
        self._inner = inner
        self._cache = cache

    def resolve_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata:
        try:
            hit = self._cache.get_film(title_hint=title_hint, year_hint=year_hint)
        except CacheError as exc:
            _LOG.warning("Film cache read failed; using network: %s", exc)
            hit = None
        if hit is not None:
            return hit
        meta = self._inner.resolve_film(title_hint=title_hint, year_hint=year_hint)
        try:
            self._cache.put_film(
                title_hint=title_hint,
                year_hint=year_hint,
                metadata=meta,
            )
        except CacheError as exc:
            _LOG.warning("Film cache write failed (ignored): %s", exc)
        return meta
