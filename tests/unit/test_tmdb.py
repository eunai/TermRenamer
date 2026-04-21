"""TMDB HTTP adapter tests (canned JSON; no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from termrenamer.api.tmdb import TmdbProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_tmdb_resolve_tv_episode() -> None:
    search_tv = _load("tmdb_search_tv.json")
    tv_detail = _load("tmdb_tv_detail.json")
    tv_ep = _load("tmdb_tv_episode.json")

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if "search/tv" in p:
            return httpx.Response(200, json=search_tv)
        if p.endswith("/tv/42") and "/season/" not in p:
            return httpx.Response(200, json=tv_detail)
        if "/tv/42/season/1/episode/1" in p:
            return httpx.Response(200, json=tv_ep)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        p = TmdbProvider(http, api_key="k", base_url="https://api.themoviedb.org/3")
        meta = p.resolve_tv_episode(show_hint="Stub", season=1, episode=1)
    assert meta == EpisodeMetadata(
        show_title="Stub Show Official",
        episode_title="Pilot",
    )


def test_tmdb_resolve_film() -> None:
    search_m = _load("tmdb_search_movie.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if "search/movie" in request.url.path:
            return httpx.Response(200, json=search_m)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        p = TmdbProvider(http, api_key="k", base_url="https://api.themoviedb.org/3")
        meta = p.resolve_film(title_hint="Stub", year_hint=2024)
    assert meta == MovieMetadata(title="Stub Movie", year=2024)


def test_tmdb_movie_missing_year_raises() -> None:
    bad = {"page": 1, "results": [{"id": 1, "title": "X", "release_date": ""}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bad)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        p = TmdbProvider(http, api_key="k", base_url="https://api.themoviedb.org/3")
        with pytest.raises(ProviderError, match="release year"):
            p.resolve_film(title_hint="X", year_hint=None)


def test_tmdb_empty_search_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        http = HttpClient(config=config, client=raw)
        p = TmdbProvider(http, api_key="k", base_url="https://api.themoviedb.org/3")
        with pytest.raises(ProviderError, match="No TMDB TV"):
            p.resolve_tv_episode(show_hint="zzz", season=1, episode=1)
