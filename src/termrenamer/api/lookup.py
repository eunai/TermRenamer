"""Per-build lookups: what planning calls, over a Provider and the optional cache.

A lookup lasts for one build. It sends each distinct question to the Provider at
most once in that build, reads and writes the SQLite cache when one is given, and
keeps the Provider seam's contract: "nothing found" is an empty tuple or ``None``,
and a failure raises :class:`~termrenamer.util.errors.ProviderError`.

Cache rules: every entry is keyed by Provider; "nothing found" is never stored; a
cache read or write that fails is logged as a warning and the lookup goes on over
the network.
"""

from __future__ import annotations

import logging

from termrenamer.api.base import BuildScopedTvProvider, FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.models import Candidate, ScanMode
from termrenamer.persistence.cache import SqliteMetadataCache, normalise_hint
from termrenamer.util.errors import CacheError

_LOG = logging.getLogger(__name__)


class _CacheAccess:
    """The cache, bound to one Provider id, with failures logged and swallowed."""

    def __init__(self, cache: SqliteMetadataCache | None, provider_id: str | None) -> None:
        if cache is not None and not provider_id:
            msg = "A lookup with a cache needs the Provider's provider_id"
            raise ValueError(msg)
        self._cache = cache
        self._provider = provider_id or ""

    def get_search(
        self, mode: ScanMode, hint: str, year: int | None
    ) -> tuple[Candidate, ...] | None:
        if self._cache is None:
            return None
        try:
            return self._cache.get_search(provider=self._provider, mode=mode, hint=hint, year=year)
        except CacheError as exc:
            _LOG.warning("Lookup cache read failed; using the network: %s", exc)
            return None

    def put_search(
        self, mode: ScanMode, hint: str, year: int | None, results: tuple[Candidate, ...]
    ) -> None:
        if self._cache is None or not results:
            return
        try:
            self._cache.put_search(
                provider=self._provider, mode=mode, hint=hint, year=year, results=results
            )
        except CacheError as exc:
            _LOG.warning("Lookup cache write failed (ignored): %s", exc)

    def get_episode(self, show_id: str, season: int, episode: int) -> str | None:
        if self._cache is None:
            return None
        try:
            return self._cache.get_episode(
                provider=self._provider, show_id=show_id, season=season, episode=episode
            )
        except CacheError as exc:
            _LOG.warning("Lookup cache read failed; using the network: %s", exc)
            return None

    def put_episode(self, show_id: str, season: int, episode: int, title: str | None) -> None:
        if self._cache is None or title is None:
            return
        try:
            self._cache.put_episode(
                provider=self._provider,
                show_id=show_id,
                season=season,
                episode=episode,
                title=title,
            )
        except CacheError as exc:
            _LOG.warning("Lookup cache write failed (ignored): %s", exc)


class TvLookup:
    """One build's TV lookups: show searches and episode titles.

    ``provider_id`` (``"tmdb"`` or ``"tvdb"``) keys the cache entries and is
    required with a cache. A Provider that keeps per-build state
    (:class:`~termrenamer.api.base.BuildScopedTvProvider`) gets one view per lookup.
    """

    def __init__(
        self,
        provider: TvMetadataProvider,
        *,
        cache: SqliteMetadataCache | None = None,
        provider_id: str | None = None,
    ) -> None:
        self._cache = _CacheAccess(cache, provider_id)
        self._provider: TvMetadataProvider = (
            provider.for_build() if isinstance(provider, BuildScopedTvProvider) else provider
        )
        self._searches: dict[str, tuple[Candidate, ...]] = {}
        self._episodes: dict[tuple[str, int, int], str | None] = {}

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        """Return the shows found for ``hint`` in the Provider's order; ``()`` is nothing found."""
        key = normalise_hint(hint)
        if key in self._searches:
            return self._searches[key]
        results = self._cache.get_search(ScanMode.TV, hint, None)
        if results is None:
            results = self._provider.search_shows(hint=hint)
            self._cache.put_search(ScanMode.TV, hint, None, results)
        self._searches[key] = results
        return results

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        """Return the episode's title; ``None`` is nothing found."""
        key = (show_id, season, episode)
        if key in self._episodes:
            return self._episodes[key]
        title = self._cache.get_episode(show_id, season, episode)
        if title is None:
            title = self._provider.episode_title(show_id=show_id, season=season, episode=episode)
            self._cache.put_episode(show_id, season, episode, title)
        self._episodes[key] = title
        return title


class FilmLookup:
    """One build's film searches, with the year retry.

    A search with a year that finds nothing is tried once more without the year;
    results found that way are stored under both year keys. ``provider_id``
    (``"tmdb"`` or ``"omdb"``) keys the cache entries and is required with a cache.
    """

    def __init__(
        self,
        provider: FilmMetadataProvider,
        *,
        cache: SqliteMetadataCache | None = None,
        provider_id: str | None = None,
    ) -> None:
        self._cache = _CacheAccess(cache, provider_id)
        self._provider = provider
        self._searches: dict[tuple[str, int | None], tuple[Candidate, ...]] = {}

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        """Return the films found in the Provider's order; ``()`` is nothing found."""
        key = (normalise_hint(hint), year)
        if key in self._searches:
            return self._searches[key]
        results = self._cache.get_search(ScanMode.FILM, hint, year)
        if results is None:
            results = self._provider.search_films(hint=hint, year=year)
            if not results and year is not None:
                _LOG.info("No film found for %r year=%s; trying without the year", hint, year)
                results = self.search_films(hint=hint, year=None)
            self._cache.put_search(ScanMode.FILM, hint, year, results)
        self._searches[key] = results
        return results
