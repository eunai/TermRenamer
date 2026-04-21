"""TheTVDB v4 adapter tests (canned JSON only; no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from termrenamer.api.tvdb_v4 import TvdbV4Provider, _tvdb_numeric_series_id
from termrenamer.core.models import EpisodeMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_resolve_episode_happy_path() -> None:
    login_j = _load("tvdb_login.json")
    search_j = _load("tvdb_search_series.json")
    eps_j = _load("tvdb_series_episodes.json")

    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if request.method == "POST" and "/login" in u:
            return httpx.Response(200, json=login_j)
        if "/search" in u and "type=series" in u:
            return httpx.Response(200, json=search_j)
        if "/episodes/default" in u:
            return httpx.Response(200, json=eps_j)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        provider = TvdbV4Provider(http, api_key="test-key", base_url="https://api4.thetvdb.com/v4")
        meta = provider.resolve_tv_episode(show_hint="Example", season=1, episode=1)
    assert meta == EpisodeMetadata(show_title="Example Show", episode_title="Pilot Episode")


def test_search_empty_raises() -> None:
    login_j = _load("tvdb_login.json")

    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if request.method == "POST" and "/login" in u:
            return httpx.Response(200, json=login_j)
        if "/search" in u:
            return httpx.Response(200, json={"status": "success", "data": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        provider = TvdbV4Provider(http, api_key="k", base_url="https://api4.thetvdb.com/v4")
        with pytest.raises(ProviderError, match="No series found"):
            provider.resolve_tv_episode(show_hint="Nothing", season=1, episode=1)


def test_401_on_search_triggers_single_relogin() -> None:
    login_j = _load("tvdb_login.json")
    search_j = _load("tvdb_search_series.json")
    eps_j = _load("tvdb_series_episodes.json")
    login_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count
        u = str(request.url)
        if request.method == "POST" and "/login" in u:
            login_count += 1
            return httpx.Response(200, json=login_j)
        if "/search" in u and "type=series" in u:
            if login_count == 1:
                return httpx.Response(401)
            return httpx.Response(200, json=search_j)
        if "/episodes/default" in u:
            return httpx.Response(200, json=eps_j)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        provider = TvdbV4Provider(http, api_key="k", base_url="https://api4.thetvdb.com/v4")
        meta = provider.resolve_tv_episode(show_hint="Example", season=1, episode=1)
    assert meta.episode_title == "Pilot Episode"
    assert login_count == 2


def test_resolve_episode_uses_tvdb_id_when_search_id_is_series_slug() -> None:
    """Live search returns ``id`` like ``series-412429``; paths require numeric ``tvdb_id``."""
    login_j = _load("tvdb_login.json")
    search_j = {
        "status": "success",
        "data": [
            {
                "objectID": "series",
                "id": "series-412429",
                "tvdb_id": 412429,
                "name": "Agatha All Along",
            },
        ],
    }
    eps_j = _load("tvdb_series_episodes.json")
    seen_episodes_url: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if request.method == "POST" and "/login" in u:
            return httpx.Response(200, json=login_j)
        if "/search" in u and "type=series" in u:
            return httpx.Response(200, json=search_j)
        if "/episodes/default" in u:
            seen_episodes_url.append(u)
            assert "/series/412429/episodes/default" in u
            assert "page=0" in u
            return httpx.Response(200, json=eps_j)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        provider = TvdbV4Provider(http, api_key="test-key", base_url="https://api4.thetvdb.com/v4")
        meta = provider.resolve_tv_episode(show_hint="Agatha All Along", season=1, episode=1)
    assert meta.show_title == "Agatha All Along"
    assert seen_episodes_url
    assert "series/412429" in seen_episodes_url[0]


def test_tvdb_numeric_series_id_prefers_tvdb_id() -> None:
    assert _tvdb_numeric_series_id({"id": "series-99", "tvdb_id": 412429, "name": "X"}) == "412429"


def test_tvdb_numeric_series_id_parses_series_prefix_without_tvdb_id() -> None:
    assert _tvdb_numeric_series_id({"id": "series-412429", "name": "X"}) == "412429"


def test_tvdb_numeric_series_id_rejects_bad_id() -> None:
    with pytest.raises(ProviderError, match="unusable"):
        _tvdb_numeric_series_id({"id": "not-a-series-id", "name": "X"})
