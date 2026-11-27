"""OMDb adapter tests — canned JSON, no live network.

OMDb's error texts used here: "Movie not found!" (already in this repo's tests) and
"Too many results." (the text the pyomdbapi wrapper compares against; not taken from
OMDb's documentation, which lists no error texts, nor from a recorded answer).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from termrenamer.api.omdb import OmdbProvider, StaticOmdbFilmMetadataProvider
from termrenamer.core.models import Candidate, MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> OmdbProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(config=HttpClientConfig(max_attempts=1), client=client)
    return OmdbProvider(http, api_key="test-key")


def _answer(data: dict[str, object], status: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status, json=data)


def test_search_returns_candidates_in_order_without_posters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _answer(_load("omdb_search_films.json"))

    results = _provider(handler).search_films(hint="Harbour Lights", year=2011)

    assert results == (
        Candidate(id="tt9000501", name="Harbour Lights", year=2011, poster_ref=None),
        Candidate(id="tt9000503", name="Harbour Lights", year=1987, poster_ref=None),
    )
    params = seen[0].url.params
    assert params["s"] == "Harbour Lights"
    assert params["y"] == "2011"
    assert params["type"] == "movie"
    assert "t" not in params


def test_search_without_year_sends_no_year() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _answer(_load("omdb_search_films.json"))

    _provider(handler).search_films(hint="Harbour Lights", year=None)
    assert "y" not in seen[0].url.params


@pytest.mark.parametrize("text", ["Movie not found!", "movie not found", "MOVIE NOT FOUND."])
def test_not_found_answer_is_nothing_found(text: str) -> None:
    provider = _provider(lambda _: _answer({"Response": "False", "Error": text}))
    assert provider.search_films(hint="ZZZZZ", year=None) == ()


@pytest.mark.parametrize("text", ["Too many results.", "too many results", "TOO MANY RESULTS!"])
def test_too_many_results_falls_back_to_the_single_title_request(text: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "s" in request.url.params:
            return _answer({"Response": "False", "Error": text})
        return _answer(_load("omdb_search_film.json"))

    results = _provider(handler).search_films(hint="The Matrix", year=1999)

    assert results == (Candidate(id="tt0133093", name="The Matrix", year=1999, poster_ref=None),)
    fallback = seen[1].url.params
    assert fallback["t"] == "The Matrix"
    assert fallback["y"] == "1999"
    assert "s" not in fallback
    assert len(seen) == 2


def test_too_many_results_then_not_found_is_nothing_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "s" in request.url.params:
            return _answer({"Response": "False", "Error": "Too many results."})
        return _answer({"Response": "False", "Error": "Movie not found!"})

    assert _provider(handler).search_films(hint="a", year=None) == ()


def test_too_many_results_then_a_title_without_a_year_is_nothing_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "s" in request.url.params:
            return _answer({"Response": "False", "Error": "Too many results."})
        return _answer({"Response": "True", "Title": "A", "Year": "N/A", "imdbID": "tt1"})

    assert _provider(handler).search_films(hint="a", year=None) == ()


def test_too_many_results_then_another_error_is_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "s" in request.url.params:
            return _answer({"Response": "False", "Error": "Too many results."})
        return _answer({"Response": "False", "Error": "Request limit reached!"})

    with pytest.raises(ProviderError, match="Request limit reached"):
        _provider(handler).search_films(hint="a", year=None)


@pytest.mark.parametrize(
    "text",
    ["Invalid API key!", "Request limit reached!", "Something went wrong.", "Movie not found here"],
)
def test_other_error_answer_is_a_failure(text: str) -> None:
    provider = _provider(lambda _: _answer({"Response": "False", "Error": text}))
    with pytest.raises(ProviderError, match="OMDb"):
        provider.search_films(hint="x", year=None)


def test_error_answer_without_a_text_is_a_failure() -> None:
    provider = _provider(lambda _: _answer({"Response": "False"}))
    with pytest.raises(ProviderError, match="OMDb"):
        provider.search_films(hint="x", year=None)


def test_search_result_without_a_usable_year_or_id_is_dropped() -> None:
    body = {
        "Response": "True",
        "Search": [
            {"Title": "No Year", "Year": "N/A", "imdbID": "tt1"},
            {"Title": "No Id", "Year": "2001"},
            {"Title": "Kept", "Year": "2002–2004", "imdbID": "tt3"},
        ],
    }
    provider = _provider(lambda _: _answer(body))
    assert provider.search_films(hint="x", year=None) == (
        Candidate(id="tt3", name="Kept", year=2002, poster_ref=None),
    )


def test_http_error_is_a_failure() -> None:
    provider = _provider(lambda _: _answer({}, status=500))
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.search_films(hint="x", year=None)


def test_unusable_search_response_is_a_failure() -> None:
    provider = _provider(lambda _: _answer({"Response": "True", "Search": "oops"}))
    with pytest.raises(ProviderError, match="Unexpected"):
        provider.search_films(hint="x", year=None)


def test_invalid_json_is_a_failure() -> None:
    provider = _provider(lambda _: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ProviderError, match="Invalid JSON"):
        provider.search_films(hint="x", year=None)


def test_static_omdb_provider() -> None:
    sp = StaticOmdbFilmMetadataProvider(
        _mapping={("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999)},
    )
    assert [c.name for c in sp.search_films(hint="The Matrix", year=1999)] == ["The Matrix"]
    assert sp.search_films(hint="unknown", year=None) == ()
