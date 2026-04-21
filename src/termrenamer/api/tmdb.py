"""TMDB adapter, static stubs for tests, and HTTP-backed provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient

_TMDB_DEFAULT_BASE = "https://api.themoviedb.org/3"


@dataclass(frozen=True, slots=True)
class StaticTvMetadataProvider:
    """Resolve episodes from an in-memory map (tests and stubs; no network)."""

    _mapping: dict[tuple[str, int, int], EpisodeMetadata]

    def resolve_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata:
        key = (show_hint.casefold().strip(), season, episode)
        try:
            return self._mapping[key]
        except KeyError as exc:
            msg = f"No stub metadata for show/season/episode={key!r}"
            raise ProviderError(msg) from exc


@dataclass(frozen=True, slots=True)
class StaticFilmMetadataProvider:
    """Resolve films from an in-memory map (tests; no network)."""

    _mapping: dict[tuple[str, int | None], MovieMetadata]

    def resolve_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata:
        key = (title_hint.casefold().strip(), year_hint)
        try:
            return self._mapping[key]
        except KeyError as exc:
            msg = f"No stub metadata for film={key!r}"
            raise ProviderError(msg) from exc


class TmdbProvider:
    """TMDB HTTP client for TV episodes and films (v3 API)."""

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str,
        base_url: str = _TMDB_DEFAULT_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key.strip()
        self._base = base_url.rstrip("/")

    def _params(self, **kwargs: str) -> dict[str, str]:
        merged = {k: v for k, v in kwargs.items() if v is not None}
        merged["api_key"] = self._api_key
        return merged

    def resolve_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata:
        search = self._get_json(
            "/search/tv",
            self._params(query=show_hint.strip()),
        )
        results = search.get("results")
        if not isinstance(results, list) or not results:
            raise ProviderError(f"No TMDB TV results for {show_hint!r}")
        first = results[0]
        if not isinstance(first, dict) or "id" not in first:
            raise ProviderError("Unexpected TMDB search/tv response")
        tv_id = int(first["id"])
        show = self._get_json(f"/tv/{tv_id}", self._params())
        show_title = show.get("name")
        if not isinstance(show_title, str) or not show_title.strip():
            raise ProviderError("TMDB TV show missing name")
        ep = self._get_json(
            f"/tv/{tv_id}/season/{season}/episode/{episode}",
            self._params(),
        )
        ep_title = ep.get("name")
        if not isinstance(ep_title, str) or not ep_title.strip():
            raise ProviderError("TMDB episode missing name")
        return EpisodeMetadata(show_title=show_title.strip(), episode_title=ep_title.strip())

    def resolve_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata:
        params = self._params(query=title_hint.strip())
        if year_hint is not None:
            params["year"] = str(year_hint)
        search = self._get_json("/search/movie", params)
        results = search.get("results")
        if not isinstance(results, list) or not results:
            raise ProviderError(f"No TMDB movie results for {title_hint!r}")
        first = results[0]
        if not isinstance(first, dict):
            raise ProviderError("Unexpected TMDB search/movie response")
        title = first.get("title") or first.get("original_title")
        rd = first.get("release_date")
        if not isinstance(title, str) or not title.strip():
            raise ProviderError("TMDB movie missing title")
        year: int | None = None
        if isinstance(rd, str) and len(rd) >= 4 and rd[:4].isdigit():
            year = int(rd[:4])
        if year is None:
            raise ProviderError("TMDB movie missing usable release year")
        return MovieMetadata(title=title.strip(), year=year)

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self._base}{path}"
        response = self._http.get(url, params=params)
        if response.status_code != 200:
            msg = f"TMDB request failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON from TMDB") from exc
        if not isinstance(data, dict):
            raise ProviderError("Unexpected JSON root from TMDB")
        return data
