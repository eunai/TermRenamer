"""TheTVDB v4 metadata adapter (HTTPS only; no filesystem)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from termrenamer.core.models import EpisodeMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient

_LOG = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api4.thetvdb.com/v4"

_SERIES_PREFIX_ID = re.compile(r"^series-(\d+)$", re.IGNORECASE)


def _tvdb_numeric_series_id(hit: dict[str, Any]) -> str:
    """Map a search hit to the numeric series id required by ``/series/{id}/...`` paths.

    Search index ``id`` values may look like ``series-412429``; episode routes expect
    the numeric **tvdb_id** field from the same hit (TheTVDB v4 API).
    """
    tvdb_id = hit.get("tvdb_id")
    if tvdb_id is not None and not isinstance(tvdb_id, bool):
        s = str(tvdb_id).strip()
        if s.isdigit():
            return s
    raw = hit.get("id")
    if raw is None:
        raise ProviderError("TheTVDB search result missing series id")
    s = str(raw).strip()
    if s.isdigit():
        return s
    m = _SERIES_PREFIX_ID.match(s)
    if m:
        return m.group(1)
    raise ProviderError("TheTVDB search result has an unusable series id")


class TvdbV4Provider:
    """Resolve TV episodes via TheTVDB v4 API."""

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
        self._base = base_url.rstrip("/")
        self._token: str | None = None

    def resolve_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata:
        """Search series, then resolve episode title from default episode list."""
        series_id, show_title = self._search_series(show_hint)
        ep_name = self._find_episode_name(series_id, season=season, episode=episode)
        return EpisodeMetadata(show_title=show_title, episode_title=ep_name)

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
            # At most one refresh attempt per §5.5: re-login and retry once.
            _LOG.debug("TheTVDB returned 401; refreshing token once")
            self._token = None
            self._login()
            headers = {"Authorization": f"Bearer {self._token}"}
            response = self._http.request(method, url, params=params, headers=headers)
        return response

    def _search_series(self, show_hint: str) -> tuple[str, str]:
        response = self._authorized_request(
            "GET",
            "/search",
            params={"query": show_hint.strip(), "type": "series"},
        )
        if response.status_code != 200:
            msg = f"TheTVDB search failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        payload = _json_or_raise(response)
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ProviderError(f"No series found for query {show_hint!r}")
        first = data[0]
        if not isinstance(first, dict):
            raise ProviderError("Unexpected TheTVDB search response shape")
        name = first.get("name")
        if not name:
            raise ProviderError("TheTVDB search result missing name")
        series_id = _tvdb_numeric_series_id(first)
        return series_id, str(name)

    def _find_episode_name(self, series_id: str, *, season: int, episode: int) -> str:
        response = self._authorized_request(
            "GET",
            f"/series/{series_id}/episodes/default",
            params={"page": "0"},
        )
        if response.status_code != 200:
            msg = f"TheTVDB episodes failed with HTTP {response.status_code}"
            raise ProviderError(msg)
        payload = _json_or_raise(response)
        episodes = _extract_episode_list(payload)
        for ep in episodes:
            if not isinstance(ep, dict):
                continue
            sn = ep.get("seasonNumber")
            num = ep.get("number")
            if sn is None or num is None:
                continue
            if int(sn) == season and int(num) == episode:
                title = ep.get("name")
                if isinstance(title, str) and title.strip():
                    return title.strip()
                raise ProviderError("Episode record missing name")
        raise ProviderError(f"No episode S{season:02d}E{episode:02d} in TheTVDB data")


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
