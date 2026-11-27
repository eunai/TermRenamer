"""No log line holds a Provider key or token: the console and the Logs view.

The Providers talk to a stand-in transport with made-up keys; no request leaves the
machine. ``TERMRENAMER_LOG_FILE`` writes no file yet (#4), so the console and the Logs
view are every place a log record reaches.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterator

import httpx
import pytest

from termrenamer.api.omdb import OmdbProvider
from termrenamer.api.tmdb import TmdbProvider
from termrenamer.api.tvdb_v4 import TvdbV4Provider
from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig
from termrenamer.util.logging import setup_logging

from .screen_driver import SIZE, make_app

_TMDB_KEY = "made-up-tmdb-key-0123456789abcdef"
_OMDB_KEY = "madeupom"
_TVDB_KEY = "made-up-tvdb-key-fedcba9876543210"
_TVDB_PIN = "4321"
_TVDB_TOKEN = "made.up.tvdb-token-for-the-test"
_SECRETS = (_TMDB_KEY, _OMDB_KEY, _TVDB_KEY, _TVDB_TOKEN)


@pytest.fixture
def bare_root() -> Iterator[logging.Logger]:
    """The root logger, restored afterwards; :func:`_strip` empties it in the test."""
    root = logging.getLogger()
    handlers, level, factory = root.handlers[:], root.level, logging.getLogRecordFactory()
    yield root
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
    logging.setLogRecordFactory(factory)


def _strip(root: logging.Logger) -> None:
    """Remove pytest's own handlers, which it adds after the fixtures, as at the app's start."""
    for handler in root.handlers[:]:
        root.removeHandler(handler)


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    config = HttpClientConfig(max_attempts=2, backoff_base_seconds=0.0, jitter=False)
    return HttpClient(config=config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _answer(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/login"):
        return httpx.Response(200, json={"status": "success", "data": {"token": _TVDB_TOKEN}})
    if "thetvdb" in request.url.host:
        return httpx.Response(200, json={"status": "success", "data": []})
    if "omdbapi" in request.url.host:
        return httpx.Response(200, json={"Response": "False", "Error": "Movie not found!"})
    return httpx.Response(200, json={"page": 1, "results": []})


def _look_up_with_every_provider() -> None:
    http = _http(_answer)
    TmdbProvider(http, api_key=_TMDB_KEY).search_shows(hint="Harbour Lights")
    OmdbProvider(http, api_key=_OMDB_KEY).search_films(hint="Harbour Lights", year=None)
    tvdb = TvdbV4Provider(http, api_key=_TVDB_KEY, subscriber_pin=_TVDB_PIN)
    tvdb.search_shows(hint="Harbour Lights")


def _log_a_failed_lookup() -> None:
    """A Provider failure whose cause quotes the request's URL, logged with its traceback."""
    url = f"https://api.themoviedb.org/3/search/tv?query=x&api_key={_TMDB_KEY}"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    try:
        _http(refuse).get(url)
    except ProviderError:
        logging.getLogger("termrenamer.test").exception("Lookup failed for %s", url)


def _assert_no_secret(text: str) -> None:
    for secret in (*_SECRETS, f"pin={_TVDB_PIN}", f'"pin": "{_TVDB_PIN}"'):
        assert secret not in text


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_the_console_shows_each_request_with_no_key_or_token(
    bare_root: logging.Logger, level: int
) -> None:
    _strip(bare_root)
    stream = io.StringIO()
    setup_logging(level=level, stream=stream)

    _look_up_with_every_provider()
    _log_a_failed_lookup()

    text = stream.getvalue()
    assert "HTTP Request: GET https://api.themoviedb.org/3/search/tv?query=Harbour" in text
    assert "HTTP Request: POST https://api4.thetvdb.com/v4/login" in text
    assert "Traceback" in text and "cannot reach" in text
    _assert_no_secret(text)


async def test_the_logs_view_shows_each_request_with_no_key_or_token(
    bare_root: logging.Logger,
) -> None:
    _strip(bare_root)
    bare_root.setLevel(logging.DEBUG)
    app = make_app()
    async with app.run_test(size=SIZE):
        _look_up_with_every_provider()
        _log_a_failed_lookup()
        text = "\n".join(line for _, line in app.log_book.lines_after(0))

    assert "HTTP Request: GET https://www.omdbapi.com?apikey=***&s=Harbour" in text
    assert "Traceback" in text and "cannot reach" in text
    _assert_no_secret(text)


def test_a_login_body_or_a_bearer_header_quoted_by_a_library_is_masked(
    bare_root: logging.Logger,
) -> None:
    _strip(bare_root)
    stream = io.StringIO()
    setup_logging(level=logging.DEBUG, stream=stream)
    library = logging.getLogger("a.library")

    library.debug("body: %s", '{"apikey": "another-made-up-key", "pin": "9876"}')
    library.debug("headers: %s", {"Authorization": "Bearer another.made-up.token"})

    text = stream.getvalue()
    assert '"apikey": "***"' in text and '"pin": "***"' in text
    assert "'Bearer ***'" in text
    for secret in ("another-made-up-key", "9876", "another.made-up.token"):
        assert secret not in text
