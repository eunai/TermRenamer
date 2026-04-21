"""OMDb adapter tests — canned JSON, no live network (spec §8)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from termrenamer.api.omdb import OmdbProvider, StaticOmdbFilmMetadataProvider
from termrenamer.core.models import MovieMetadata
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig

_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "api_responses" / "omdb_search_film.json"
)


def _canned_response(data: dict[str, object], status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=data,
        request=httpx.Request("GET", "https://www.omdbapi.com/"),
    )


def _make_provider(responses: list[httpx.Response]) -> OmdbProvider:
    transport = httpx.MockTransport(lambda _: responses.pop(0))
    client = httpx.Client(transport=transport)
    http = HttpClient(config=HttpClientConfig(max_attempts=1), client=client)
    return OmdbProvider(http, api_key="test-key")


def test_omdb_resolve_film() -> None:
    data = json.loads(_FIXTURE.read_text())
    provider = _make_provider([_canned_response(data)])
    result = provider.resolve_film(title_hint="The Matrix", year_hint=1999)
    assert result == MovieMetadata(title="The Matrix", year=1999)


def test_omdb_resolve_film_no_year_hint() -> None:
    data = json.loads(_FIXTURE.read_text())
    provider = _make_provider([_canned_response(data)])
    result = provider.resolve_film(title_hint="The Matrix", year_hint=None)
    assert result.title == "The Matrix"
    assert result.year == 1999


def test_omdb_not_found_raises() -> None:
    data = {"Response": "False", "Error": "Movie not found!"}
    provider = _make_provider([_canned_response(data)])
    with pytest.raises(ProviderError, match="Movie not found"):
        provider.resolve_film(title_hint="ZZZZZ", year_hint=None)


def test_omdb_missing_title_raises() -> None:
    data = {"Response": "True", "Year": "2020"}
    provider = _make_provider([_canned_response(data)])
    with pytest.raises(ProviderError, match="missing Title"):
        provider.resolve_film(title_hint="x", year_hint=None)


def test_omdb_missing_year_raises() -> None:
    data = {"Response": "True", "Title": "X", "Year": "N/A"}
    provider = _make_provider([_canned_response(data)])
    with pytest.raises(ProviderError, match="missing usable Year"):
        provider.resolve_film(title_hint="x", year_hint=None)


def test_omdb_http_error_raises() -> None:
    provider = _make_provider([_canned_response({}, status=500)])
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.resolve_film(title_hint="x", year_hint=None)


def test_static_omdb_provider() -> None:
    sp = StaticOmdbFilmMetadataProvider(
        _mapping={("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999)},
    )
    assert sp.resolve_film(title_hint="The Matrix", year_hint=1999).title == "The Matrix"
    with pytest.raises(ProviderError):
        sp.resolve_film(title_hint="unknown", year_hint=None)
