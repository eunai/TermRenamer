"""TMDB adapter, static stand-ins for tests, and the HTTP-backed Provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from termrenamer.api.base import id_field, leading_year, text_field
from termrenamer.core.models import Candidate, EpisodeMetadata, MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient
from termrenamer.util.logging import keep_out_of_logs

_TMDB_DEFAULT_BASE = "https://api.themoviedb.org/3"


def _norm(hint: str) -> str:
    return hint.casefold().strip()


@dataclass(frozen=True, slots=True)
class StaticTvMetadataProvider:
    """Answer TV lookups from an in-memory map (tests and stubs; no network).

    The map is keyed by (normalised show hint, season, episode). A hint with any
    entry finds one show, whose id is the normalised hint and whose name is the
    first entry's show title. Anything else is nothing found.
    """

    _mapping: dict[tuple[str, int, int], EpisodeMetadata]

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        key = _norm(hint)
        for (show, _season, _episode), meta in self._mapping.items():
            if show == key:
                return (Candidate(id=key, name=meta.show_title, year=None),)
        return ()

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        meta = self._mapping.get((show_id, season, episode))
        return meta.episode_title if meta is not None else None


@dataclass(frozen=True, slots=True)
class StaticFilmMetadataProvider:
    """Answer film searches from an in-memory map (tests; no network).

    The map is keyed by (normalised title hint, year hint); a key that is present
    finds that one film, and anything else is nothing found.
    """

    _mapping: dict[tuple[str, int | None], MovieMetadata]

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        meta = self._mapping.get((_norm(hint), year))
        if meta is None:
            return ()
        film_id = f"{_norm(meta.title)}|{meta.year}"
        return (Candidate(id=film_id, name=meta.title, year=meta.year),)


class TmdbProvider:
    """TMDB HTTP client for TV and films (v3 API)."""

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str,
        base_url: str = _TMDB_DEFAULT_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key.strip()
        keep_out_of_logs(self._api_key)
        self._base = base_url.rstrip("/")

    def _params(self, **kwargs: str) -> dict[str, str]:
        merged = dict(kwargs)
        merged["api_key"] = self._api_key
        return merged

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        """Search TV shows; each result's year is its first-aired year when known."""
        results = _results(self._get_json("/search/tv", self._params(query=hint.strip())))
        found: list[Candidate] = []
        for item in results:
            show_id = id_field(item, "id")
            name = text_field(item, "name", "original_name")
            if show_id is None or name is None:
                continue
            found.append(
                Candidate(
                    id=show_id,
                    name=name,
                    year=leading_year(item.get("first_air_date")),
                    poster_ref=text_field(item, "poster_path"),
                ),
            )
        return tuple(found)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        """Return the episode's name; TMDB's HTTP 404 on the episode is nothing found."""
        path = f"/tv/{show_id}/season/{season}/episode/{episode}"
        data = self._get_json(path, self._params(), not_found_ok=True)
        if data is None:
            return None
        title = text_field(data, "name")
        if title is None:
            raise ProviderError("TMDB episode missing name")
        return title

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        """Search films; a result without a usable release year is dropped."""
        params = self._params(query=hint.strip())
        if year is not None:
            params["year"] = str(year)
        results = _results(self._get_json("/search/movie", params))
        found: list[Candidate] = []
        for item in results:
            film_id = id_field(item, "id")
            title = text_field(item, "title", "original_title")
            film_year = leading_year(item.get("release_date"))
            if film_id is None or title is None or film_year is None:
                continue
            found.append(
                Candidate(
                    id=film_id,
                    name=title,
                    year=film_year,
                    poster_ref=text_field(item, "poster_path"),
                ),
            )
        return tuple(found)

    def _get_json(
        self,
        path: str,
        params: dict[str, str],
        *,
        not_found_ok: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{self._base}{path}"
        response = self._http.get(url, params=params)
        if response.status_code == 404 and not_found_ok:
            return None
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


def _results(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return a search response's result records; a missing list is unusable."""
    results = data.get("results") if data is not None else None
    if not isinstance(results, list):
        raise ProviderError("Unexpected TMDB search response")
    return [item for item in results if isinstance(item, dict)]
