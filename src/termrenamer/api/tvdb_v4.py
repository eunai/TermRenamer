"""TheTVDB v4 metadata adapter (HTTPS only; no filesystem)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from termrenamer.api.base import TvMetadataProvider, leading_year, text_field
from termrenamer.core.models import Candidate
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient
from termrenamer.util.logging import keep_out_of_logs

_LOG = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api4.thetvdb.com/v4"

_SERIES_PREFIX_ID = re.compile(r"^series-(\d+)$", re.IGNORECASE)


def _tvdb_numeric_series_id(hit: dict[str, Any]) -> str | None:
    """Map a search hit to the numeric series id required by ``/series/{id}/...`` paths.

    Search index ``id`` values may look like ``series-412429``; episode routes expect
    the numeric **tvdb_id** field from the same hit (TheTVDB v4 API). Returns ``None``
    when the hit has no usable id.
    """
    tvdb_id = hit.get("tvdb_id")
    if tvdb_id is not None and not isinstance(tvdb_id, bool):
        s = str(tvdb_id).strip()
        if s.isdigit():
            return s
    raw = hit.get("id")
    if raw is None:
        return None
    s = str(raw).strip()
    if s.isdigit():
        return s
    m = _SERIES_PREFIX_ID.match(s)
    if m:
        return m.group(1)
    return None


class TvdbV4Provider:
    """TV Provider over TheTVDB v4 API: series search and the default episode list."""

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str,
        subscriber_pin: str | None = None,
        base_url: str = _DEFAULT_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key.strip()
        self._pin = subscriber_pin.strip() if subscriber_pin else None
        keep_out_of_logs(self._api_key, self._pin)
        self._base = base_url.rstrip("/")
        self._token: str | None = None

    def for_build(self) -> TvMetadataProvider:
        """Return a view for one build that fetches each show's episode list once."""
        return _TvdbBuild(self)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        """Search series; a hit without a usable id or name is dropped."""
        response = self._authorized_request(
            "GET",
            "/search",
            params={"query": hint.strip(), "type": "series"},
        )
        if response.status_code != 200:
            msg = f"TheTVDB search failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        data = _json_or_raise(response).get("data")
        if not isinstance(data, list):
            raise ProviderError("Unexpected TheTVDB search response shape")
        found: list[Candidate] = []
        for hit in data:
            if not isinstance(hit, dict):
                continue
            series_id = _tvdb_numeric_series_id(hit)
            name = text_field(hit, "name")
            if series_id is None or name is None:
                continue
            year = leading_year(hit.get("year")) or leading_year(hit.get("first_air_time"))
            found.append(
                Candidate(
                    id=series_id,
                    name=name,
                    year=year,
                    poster_ref=text_field(hit, "image_url", "thumbnail"),
                ),
            )
        return tuple(found)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        """Return the episode's name from the show's default episode list.

        A list without the episode is nothing found. Each call fetches the list;
        :meth:`for_build` gives a view that fetches it once per show.
        """
        return _title_in(self.episode_index(show_id), season=season, episode=episode)

    def episode_index(self, show_id: str) -> dict[tuple[int, int], str | None]:
        """Fetch a show's default episode list as (season, number) -> name or ``None``."""
        response = self._authorized_request(
            "GET",
            f"/series/{show_id}/episodes/default",
            params={"page": "0"},
        )
        if response.status_code != 200:
            msg = f"TheTVDB episodes failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        index: dict[tuple[int, int], str | None] = {}
        for ep in _extract_episode_list(_json_or_raise(response)):
            if not isinstance(ep, dict):
                continue
            sn = _whole_number(ep.get("seasonNumber"))
            num = _whole_number(ep.get("number"))
            if sn is None or num is None:
                continue
            index.setdefault((sn, num), text_field(ep, "name"))
        return index

    def _login(self) -> None:
        body: dict[str, str] = {"apikey": self._api_key}
        if self._pin:
            body["pin"] = self._pin
        url = f"{self._base}/login"
        response = self._http.post(url, json=body, headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            msg = f"TheTVDB login failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        payload = _json_or_raise(response)
        token = _extract_token(payload)
        if not token:
            raise ProviderError("TheTVDB login response missing token")
        keep_out_of_logs(token)
        self._token = token

    def _ensure_token(self) -> None:
        if self._token is None:
            self._login()

    def _authorized_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._ensure_token()
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        response = self._http.request(method, url, params=params, headers=headers)
        if response.status_code == 401:
            # At most one refresh attempt: re-login and retry once.
            _LOG.debug("TheTVDB returned 401; refreshing token once")
            self._token = None
            self._login()
            headers = {"Authorization": f"Bearer {self._token}"}
            response = self._http.request(method, url, params=params, headers=headers)
        return response


class _TvdbBuild:
    """One build's view of :class:`TvdbV4Provider`: each episode list fetched once."""

    def __init__(self, provider: TvdbV4Provider) -> None:
        self._provider = provider
        self._indexes: dict[str, dict[tuple[int, int], str | None]] = {}

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        return self._provider.search_shows(hint=hint)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        index = self._indexes.get(show_id)
        if index is None:
            index = self._provider.episode_index(show_id)
            self._indexes[show_id] = index
        return _title_in(index, season=season, episode=episode)


def _whole_number(value: object) -> int | None:
    """Read an episode list's season or episode number (a number or digits)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _title_in(
    index: dict[tuple[int, int], str | None],
    *,
    season: int,
    episode: int,
) -> str | None:
    if (season, episode) not in index:
        return None
    title = index[(season, episode)]
    if title is None:
        raise ProviderError("Episode record missing name")
    return title


def _json_or_raise(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ProviderError("Invalid JSON from TheTVDB") from exc
    if not isinstance(data, dict):
        raise ProviderError("Unexpected JSON root from TheTVDB")
    return data


def _extract_token(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        token = data.get("token")
        if isinstance(token, str):
            return token
    return None


def _extract_episode_list(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        eps = data.get("episodes")
        if isinstance(eps, list):
            return eps
    if isinstance(data, list):
        return data
    return []
