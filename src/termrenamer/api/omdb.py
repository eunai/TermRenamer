"""OMDb API adapter — optional film metadata fallback (spec §9 P2-01)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from termrenamer.core.models import MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient

_LOG = logging.getLogger(__name__)
_OMDB_BASE = "https://www.omdbapi.com/"


@dataclass(frozen=True, slots=True)
class StaticOmdbFilmMetadataProvider:
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
            msg = f"No stub OMDb metadata for film={key!r}"
            raise ProviderError(msg) from exc


class OmdbProvider:
    """OMDb HTTP client for film title/year resolution (v1 API, JSON mode)."""

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str,
        base_url: str = _OMDB_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key.strip()
        self._base = base_url.rstrip("/")

    def resolve_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata:
        """Search OMDb by title (and optional year) and return resolved metadata."""
        params: dict[str, str] = {
            "apikey": self._api_key,
            "t": title_hint.strip(),
            "type": "movie",
        }
        if year_hint is not None:
            params["y"] = str(year_hint)

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

        if data.get("Response") == "False":
            error = data.get("Error", "Unknown error")
            raise ProviderError(f"OMDb: {error}")

        title = data.get("Title")
        if not isinstance(title, str) or not title.strip():
            raise ProviderError("OMDb response missing Title")

        year_raw = data.get("Year")
        year: int | None = None
        if isinstance(year_raw, str) and len(year_raw) >= 4 and year_raw[:4].isdigit():
            year = int(year_raw[:4])
        if year is None:
            raise ProviderError("OMDb response missing usable Year")

        return MovieMetadata(title=title.strip(), year=year)
