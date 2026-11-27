"""OMDb API adapter: a Film Provider the user selects in Film mode."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from termrenamer.api.base import leading_year, text_field
from termrenamer.api.tmdb import StaticFilmMetadataProvider
from termrenamer.core.models import Candidate, MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient
from termrenamer.util.logging import keep_out_of_logs

_LOG = logging.getLogger(__name__)
_OMDB_BASE = "https://www.omdbapi.com/"

# OMDb's error texts, compared by :func:`_error_key`. OMDb's own page lists none:
# "Movie not found!" is in this repo's tests, and "Too many results." is the text the
# pyomdbapi wrapper compares against. Neither comes from a recorded answer.
_NOT_FOUND = "movie not found"
_TOO_MANY = "too many results"


def _error_key(text: str) -> str:
    """Compare error texts without regard to case, outer spaces or final ``.`` / ``!``."""
    return text.strip().rstrip(".!").strip().casefold()


@dataclass(frozen=True, slots=True)
class StaticOmdbFilmMetadataProvider:
    """Answer film searches from an in-memory map (tests; no network)."""

    _mapping: dict[tuple[str, int | None], MovieMetadata]

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        return StaticFilmMetadataProvider(_mapping=self._mapping).search_films(
            hint=hint,
            year=year,
        )


class OmdbProvider:
    """OMDb HTTP client for film searches (v1 API, JSON mode).

    Results carry no Poster reference.
    """

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str,
        base_url: str = _OMDB_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key.strip()
        keep_out_of_logs(self._api_key)
        self._base = base_url.rstrip("/")

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        """Search OMDb by title (and optional year); a result without a usable year is dropped.

        OMDb's "not found" answer is nothing found. Its "too many results" answer falls
        back to the single-title request, which returns that one film or nothing found.
        """
        data = self._get({"s": hint.strip()}, year=year)
        error = _error_of(data)
        if error is not None:
            if error == _TOO_MANY:
                return self._single_title(hint, year=year)
            return _not_found_or_raise(data, error)
        results = data.get("Search")
        if not isinstance(results, list):
            raise ProviderError("Unexpected OMDb search response")
        found = (_candidate(item) for item in results if isinstance(item, dict))
        return tuple(c for c in found if c is not None)

    def _single_title(self, hint: str, *, year: int | None) -> tuple[Candidate, ...]:
        data = self._get({"t": hint.strip()}, year=year)
        error = _error_of(data)
        if error is not None:
            return _not_found_or_raise(data, error)
        candidate = _candidate(data)
        return (candidate,) if candidate is not None else ()

    def _get(self, query: dict[str, str], *, year: int | None) -> dict[str, Any]:
        params = {"apikey": self._api_key, **query, "type": "movie"}
        if year is not None:
            params["y"] = str(year)
        response = self._http.get(self._base, params=params)
        if response.status_code != 200:
            msg = f"OMDb request failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON from OMDb") from exc
        if not isinstance(data, dict):
            raise ProviderError("Unexpected JSON root from OMDb")
        return data


def _error_of(data: dict[str, Any]) -> str | None:
    """Return the compared error text of a ``Response: False`` answer, else ``None``."""
    if data.get("Response") != "False":
        return None
    error = data.get("Error")
    return _error_key(error) if isinstance(error, str) else ""


def _not_found_or_raise(data: dict[str, Any], error: str) -> tuple[Candidate, ...]:
    if error == _NOT_FOUND:
        return ()
    raw = data.get("Error")
    shown = raw.strip() if isinstance(raw, str) and raw.strip() else "Unknown error"
    raise ProviderError(f"OMDb: {shown}")


def _candidate(item: dict[str, Any]) -> Candidate | None:
    film_id = text_field(item, "imdbID")
    title = text_field(item, "Title")
    year = leading_year(item.get("Year"))
    if film_id is None or title is None or year is None:
        return None
    return Candidate(id=film_id, name=title, year=year)
