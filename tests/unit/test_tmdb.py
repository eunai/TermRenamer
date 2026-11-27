"""TMDB HTTP adapter tests (canned JSON; no live network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from termrenamer.api.tmdb import TmdbProvider
from termrenamer.core.models import Candidate
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> TmdbProvider:
    config = HttpClientConfig(max_attempts=1, backoff_base_seconds=0.01, jitter=False)
    raw = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(config=config, client=raw)
    return TmdbProvider(http, api_key="k", base_url="https://api.themoviedb.org/3")


def test_film_search_returns_candidates_in_order_with_posters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_load("tmdb_search_movie_candidates.json"))

    results = _provider(handler).search_films(hint="Harbour Lights", year=2011)

    assert results == (
        Candidate(
            id="501", name="Harbour Lights", year=2011, poster_ref="/harbour-lights-2011.jpg"
        ),
        Candidate(id="503", name="Harbour Lights", year=1987, poster_ref=None),
    )
    assert seen[0].url.path == "/3/search/movie"
    assert seen[0].url.params["query"] == "Harbour Lights"
    assert seen[0].url.params["year"] == "2011"


def test_film_search_without_year_sends_no_year() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_load("tmdb_search_movie.json"))

    results = _provider(handler).search_films(hint="Stub", year=None)

    assert [c.name for c in results] == ["Stub Movie"]
    assert "year" not in seen[0].url.params


def test_film_search_with_no_results_is_nothing_found() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"page": 1, "results": []}))
    assert provider.search_films(hint="zzz", year=None) == ()


def test_film_search_where_no_result_has_a_year_is_nothing_found() -> None:
    body = {"page": 1, "results": [{"id": 1, "title": "X", "release_date": ""}]}
    provider = _provider(lambda _: httpx.Response(200, json=body))
    assert provider.search_films(hint="X", year=None) == ()


def test_tv_search_returns_candidates_in_order_with_posters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_load("tmdb_search_tv_candidates.json"))

    results = _provider(handler).search_shows(hint="Quiet Valley")

    assert results == (
        Candidate(id="7001", name="Quiet Valley", year=2019, poster_ref="/quiet-valley.jpg"),
        Candidate(id="7002", name="Quiet Valley Stories", year=None, poster_ref=None),
    )
    assert seen[0].url.path == "/3/search/tv"
    assert seen[0].url.params["query"] == "Quiet Valley"


def test_tv_search_with_no_results_is_nothing_found() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"results": []}))
    assert provider.search_shows(hint="zzz") == ()


def test_episode_title_for_show_id_season_and_episode() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=_load("tmdb_tv_episode.json"))

    title = _provider(handler).episode_title(show_id="42", season=1, episode=1)

    assert title == "Pilot"
    assert seen == ["/3/tv/42/season/1/episode/1"]


def test_episode_http_404_is_nothing_found() -> None:
    provider = _provider(lambda _: httpx.Response(404, json={"status_code": 34}))
    assert provider.episode_title(show_id="42", season=9, episode=99) is None


@pytest.mark.parametrize("status", [401, 404, 500])
def test_search_non_success_answer_is_a_failure(status: int) -> None:
    provider = _provider(lambda _: httpx.Response(status, json={}))
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        provider.search_shows(hint="x")
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        provider.search_films(hint="x", year=None)


@pytest.mark.parametrize("status", [401, 500])
def test_episode_non_success_answer_other_than_404_is_a_failure(status: int) -> None:
    provider = _provider(lambda _: httpx.Response(status, json={}))
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        provider.episode_title(show_id="42", season=1, episode=1)


def test_unusable_search_response_is_a_failure() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"page": 1}))
    with pytest.raises(ProviderError):
        provider.search_shows(hint="x")
    with pytest.raises(ProviderError):
        provider.search_films(hint="x", year=None)


def test_episode_without_a_name_is_a_failure() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"id": 1, "name": ""}))
    with pytest.raises(ProviderError, match="missing name"):
        provider.episode_title(show_id="42", season=1, episode=1)


def test_invalid_json_is_a_failure() -> None:
    provider = _provider(lambda _: httpx.Response(200, content=b"not json"))
    with pytest.raises(ProviderError, match="Invalid JSON"):
        provider.search_shows(hint="x")
