"""TheTVDB v4 adapter tests (canned JSON only; no live network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from termrenamer.api.base import BuildScopedTvProvider
from termrenamer.api.tvdb_v4 import TvdbV4Provider, _tvdb_numeric_series_id
from termrenamer.core.models import Candidate
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> TvdbV4Provider:
    config = HttpClientConfig(max_attempts=1, backoff_base_seconds=0.01, jitter=False)
    raw = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(config=config, client=raw)
    return TvdbV4Provider(http, api_key="test-key", base_url="https://api4.thetvdb.com/v4")


def _routes(
    *,
    search: dict | None = None,
    episodes: dict | None = None,
    episode_requests: list[str] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if request.method == "POST" and "/login" in u:
            return httpx.Response(200, json=_load("tvdb_login.json"))
        if "/search" in u and "type=series" in u and search is not None:
            return httpx.Response(200, json=search)
        if "/episodes/default" in u and episodes is not None:
            if episode_requests is not None:
                episode_requests.append(request.url.path)
            return httpx.Response(200, json=episodes)
        return httpx.Response(404)

    return handler


def test_search_returns_candidates_in_order_with_posters() -> None:
    provider = _provider(_routes(search=_load("tvdb_search_series_candidates.json")))

    results = provider.search_shows(hint="Quiet Valley")

    assert results == (
        Candidate(
            id="81001",
            name="Quiet Valley",
            year=2019,
            poster_ref="https://artworks.thetvdb.com/banners/posters/81001-1.jpg",
        ),
        Candidate(id="81002", name="Quiet Valley (1994)", year=1994, poster_ref=None),
    )


def test_search_with_no_results_is_nothing_found() -> None:
    provider = _provider(_routes(search={"status": "success", "data": []}))
    assert provider.search_shows(hint="Nothing") == ()


def test_episode_title_from_the_episode_list() -> None:
    provider = _provider(_routes(episodes=_load("tvdb_series_episodes.json")))
    assert provider.episode_title(show_id="12345", season=1, episode=1) == "Pilot Episode"


def test_episode_list_without_the_episode_is_nothing_found() -> None:
    provider = _provider(_routes(episodes=_load("tvdb_series_episodes.json")))
    assert provider.episode_title(show_id="12345", season=4, episode=2) is None


def test_episode_numbers_given_as_text_are_read() -> None:
    episodes = {"data": {"episodes": [{"seasonNumber": "2", "number": "3", "name": "Thaw"}]}}
    provider = _provider(_routes(episodes=episodes))
    assert provider.episode_title(show_id="12345", season=2, episode=3) == "Thaw"


def test_episode_in_the_list_without_a_name_is_a_failure() -> None:
    episodes = {"data": {"episodes": [{"seasonNumber": 1, "number": 1, "name": None}]}}
    provider = _provider(_routes(episodes=episodes))
    with pytest.raises(ProviderError, match="missing name"):
        provider.episode_title(show_id="12345", season=1, episode=1)


def test_a_build_fetches_a_shows_episode_list_once() -> None:
    requests: list[str] = []
    provider = _provider(
        _routes(episodes=_load("tvdb_series_episodes.json"), episode_requests=requests),
    )
    assert isinstance(provider, BuildScopedTvProvider)

    build = provider.for_build()
    assert build.episode_title(show_id="12345", season=1, episode=1) == "Pilot Episode"
    assert build.episode_title(show_id="12345", season=1, episode=2) is None
    assert build.episode_title(show_id="12345", season=1, episode=1) == "Pilot Episode"
    assert requests == ["/v4/series/12345/episodes/default"]

    next_build = provider.for_build()
    assert next_build.episode_title(show_id="12345", season=1, episode=1) == "Pilot Episode"
    assert len(requests) == 2


def test_a_build_searches_through_the_provider() -> None:
    provider = _provider(_routes(search=_load("tvdb_search_series_candidates.json")))
    assert provider.for_build().search_shows(hint="Quiet Valley")[0].id == "81001"


@pytest.mark.parametrize("status", [400, 404, 500])
def test_search_non_success_answer_is_a_failure(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_load("tvdb_login.json"))
        return httpx.Response(status, json={})

    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        _provider(handler).search_shows(hint="x")


@pytest.mark.parametrize("status", [404, 500])
def test_episode_list_non_success_answer_is_a_failure(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_load("tvdb_login.json"))
        return httpx.Response(status, json={})

    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        _provider(handler).episode_title(show_id="1", season=1, episode=1)


def test_failed_login_is_a_failure() -> None:
    provider = _provider(lambda _: httpx.Response(401, json={}))
    with pytest.raises(ProviderError, match="login failed"):
        provider.search_shows(hint="x")


def test_unusable_search_response_is_a_failure() -> None:
    provider = _provider(_routes(search={"status": "success", "data": {"oops": 1}}))
    with pytest.raises(ProviderError):
        provider.search_shows(hint="x")


def test_401_on_search_triggers_single_relogin() -> None:
    login_j = _load("tvdb_login.json")
    search_j = _load("tvdb_search_series.json")
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
        return httpx.Response(404)

    results = _provider(handler).search_shows(hint="Example")
    assert [c.name for c in results] == ["Example Show"]
    assert login_count == 2


def test_episode_list_uses_tvdb_id_when_search_id_is_series_slug() -> None:
    """Live search returns ``id`` like ``series-412429``; paths require numeric ``tvdb_id``."""
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
    requests: list[str] = []
    provider = _provider(
        _routes(
            search=search_j,
            episodes=_load("tvdb_series_episodes.json"),
            episode_requests=requests,
        ),
    )
    (show,) = provider.search_shows(hint="Agatha All Along")
    assert show.id == "412429"
    provider.episode_title(show_id=show.id, season=1, episode=1)
    assert requests == ["/v4/series/412429/episodes/default"]


def test_search_result_without_a_usable_id_is_dropped() -> None:
    search_j = {
        "data": [
            {"id": "not-a-series-id", "name": "Broken"},
            {"id": "series-7", "name": "Kept"},
        ],
    }
    provider = _provider(_routes(search=search_j))
    assert [c.name for c in provider.search_shows(hint="x")] == ["Kept"]


def test_tvdb_numeric_series_id_prefers_tvdb_id() -> None:
    assert _tvdb_numeric_series_id({"id": "series-99", "tvdb_id": 412429, "name": "X"}) == "412429"


def test_tvdb_numeric_series_id_parses_series_prefix_without_tvdb_id() -> None:
    assert _tvdb_numeric_series_id({"id": "series-412429", "name": "X"}) == "412429"


def test_tvdb_numeric_series_id_rejects_bad_id() -> None:
    assert _tvdb_numeric_series_id({"id": "not-a-series-id", "name": "X"}) is None
