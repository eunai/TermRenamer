"""No log line holds a Provider key or token: the console and the Logs view.

Two layers (:mod:`termrenamer.util.logging`): no record quotes a key, the PIN or
TheTVDB's login body, checked through a handler that masks nothing; and the console and
the Logs view mask each registered key and token whatever quotes it. The Providers talk
to a stand-in transport with made-up keys; no request leaves the machine.
``TERMRENAMER_LOG_FILE`` writes no file yet (#4), so the console and the Logs view are
every place a log line reaches.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from termrenamer.api.omdb import OmdbProvider
from termrenamer.api.tmdb import TmdbProvider
from termrenamer.api.tvdb_v4 import TvdbV4Provider
from termrenamer.tui.log_book import LogBook, LogBookHandler
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


class _Raw(logging.Handler):
    """Every record as a plain formatter writes it, traceback included: nothing masked."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def bare_root() -> Iterator[logging.Logger]:
    """The root logger, restored afterwards; :func:`_strip` empties it in the test."""
    root = logging.getLogger()
    handlers, level, factory = root.handlers[:], root.level, logging.getLogRecordFactory()
    quiet = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    yield root
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
    logging.setLogRecordFactory(factory)
    for name, was in quiet.items():
        logging.getLogger(name).setLevel(was)


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


def _refused_lookup() -> None:
    """A request the transport refuses, with the key in its query, as a Provider sends it."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot reach the host", request=request)

    with pytest.raises(ProviderError):
        _http(refuse).get("https://api.themoviedb.org/3/search/tv", params={"api_key": _TMDB_KEY})


class _Changing:
    """A lazy log argument that gives harmless text first and a key the next time."""

    def __init__(self) -> None:
        self.calls = 0

    def __str__(self) -> str:
        self.calls += 1
        return "nothing secret" if self.calls == 1 else f"the key {_TMDB_KEY}"


def _quote_every_secret() -> None:
    """Log each key and token without a field name, as an error message might quote it."""
    log = logging.getLogger("a.library")
    log.warning("keys: %s %s %s", _TMDB_KEY, _OMDB_KEY, _TVDB_KEY)
    log.warning("token: %s", _TVDB_TOKEN)
    log.warning("lazy: %s", _Changing())
    log.warning("%d is not a number", _TMDB_KEY)  # cannot be formatted
    try:
        try:
            raise OSError(f"cannot reach https://example.invalid/?k={_OMDB_KEY}")
        except OSError as cause:
            raise ProviderError(f"lookup failed for {_TVDB_KEY}") from cause
    except ProviderError:
        log.exception("Lookup failed")


def _with_text_preformatted(secret: str) -> Callable[..., logging.LogRecord]:
    """A record factory, as another library might install, that fills in the traceback and
    the stack itself with ``secret`` in them."""
    current = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        record.exc_text = f"Traceback: {secret}"
        record.stack_info = f"Stack: {secret}"
        return record

    return factory


def _assert_no_secret(text: str) -> None:
    for secret in _SECRETS:
        assert secret not in text


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_no_record_quotes_a_key_the_pin_the_token_or_the_login_body(
    bare_root: logging.Logger, level: int
) -> None:
    _strip(bare_root)
    setup_logging(level=level, stream=io.StringIO())
    raw = _Raw()
    bare_root.addHandler(raw)

    _look_up_with_every_provider()
    _refused_lookup()

    text = "\n".join(raw.lines)
    assert "termrenamer.util.http: HTTP GET https://api.themoviedb.org/3/search/tv 200" in text
    assert "HTTP GET https://www.omdbapi.com/ 200" in text
    assert "HTTP POST https://api4.thetvdb.com/v4/login 200" in text
    _assert_no_secret(text)
    assert _TVDB_PIN not in text and '"pin"' not in text and "apikey" not in text


def test_the_console_masks_each_key_and_token_whatever_quotes_it(
    bare_root: logging.Logger,
) -> None:
    _strip(bare_root)
    stream = io.StringIO()
    setup_logging(level=logging.DEBUG, stream=stream)

    _look_up_with_every_provider()
    _quote_every_secret()
    logging.setLogRecordFactory(_with_text_preformatted(_TMDB_KEY))
    logging.getLogger("a.library").warning("preformatted")

    text = stream.getvalue()
    assert "keys: *** *** ***" in text and "token: ***" in text
    assert "a log line could not be written" in text
    assert "Traceback" in text and "lookup failed for ***" in text
    assert "Traceback: ***" in text and "Stack: ***" in text
    _assert_no_secret(text)


async def test_the_logs_view_masks_each_key_and_token_whatever_quotes_it(
    bare_root: logging.Logger,
) -> None:
    _strip(bare_root)
    bare_root.setLevel(logging.DEBUG)
    app = make_app()
    async with app.run_test(size=SIZE):
        _look_up_with_every_provider()
        _refused_lookup()
        _quote_every_secret()
        text = "\n".join(line for _, line in app.log_book.lines_after(0))

    assert "HTTP GET https://www.omdbapi.com/ 200" in text
    assert "keys: *** *** ***" in text and "token: ***" in text
    assert "Traceback" in text and "lookup failed for ***" in text
    _assert_no_secret(text)
    assert "HTTP Request:" not in text


def test_a_redirect_is_logged_as_the_request_the_app_made(bare_root: logging.Logger) -> None:
    _strip(bare_root)
    setup_logging(level=logging.DEBUG, stream=io.StringIO())
    raw = _Raw()
    bare_root.addHandler(raw)

    def redirect(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(307, headers={"Location": f"/v4/elsewhere/{_TVDB_PIN}"})
        return httpx.Response(200, json={"status": "success", "data": {"token": _TVDB_TOKEN}})

    http = HttpClient(
        config=HttpClientConfig(max_attempts=1),
        client=httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=True),
    )
    tvdb = TvdbV4Provider(http, api_key=_TVDB_KEY, subscriber_pin=_TVDB_PIN)
    with pytest.raises(ProviderError) as caught:
        tvdb.search_shows(hint="Harbour Lights")

    text = "\n".join(raw.lines)
    assert "HTTP POST https://api4.thetvdb.com/v4/login 307" in text
    assert _TVDB_PIN not in text and "elsewhere" not in text
    assert str(caught.value) == "HTTP 307 redirect from api4.thetvdb.com not followed"


class _Unprintable(Exception):
    def __str__(self) -> str:
        raise _Unprintable


class _Refuses:
    """A log argument that cannot be made into text, with an error that cannot either."""

    def __str__(self) -> str:
        raise _Unprintable


def test_a_line_that_cannot_be_written_shows_no_key_on_any_stream(
    bare_root: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    _strip(bare_root)
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    setup_logging(level=logging.DEBUG, stream=stream)
    TmdbProvider(_http(_answer), api_key=_TMDB_KEY)
    log = logging.getLogger("a.library")

    log.warning("%s %s", _TMDB_KEY, _Refuses())
    log.warning("→ %s", _TMDB_KEY)  # the ascii stream refuses the arrow

    stream.flush()
    written = stream.buffer.getvalue().decode("ascii")  # type: ignore[attr-defined]
    assert written.count("WARNING a.library: a log line could not be written") == 2
    captured = capsys.readouterr()
    for text in (written, captured.out, captured.err):
        assert _TMDB_KEY not in text


async def test_the_logs_view_writes_no_key_when_a_line_cannot_be_written(
    bare_root: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    _strip(bare_root)
    app = make_app()
    async with app.run_test(size=SIZE):
        TmdbProvider(_http(_answer), api_key=_TMDB_KEY)
        logging.getLogger("a.library").warning("%s %s", _TMDB_KEY, _Refuses())
        text = "\n".join(line for _, line in app.log_book.lines_after(0))

    assert "WARNING a.library: a log line could not be written" in text
    captured = capsys.readouterr()
    for shown in (text, captured.out, captured.err):
        assert _TMDB_KEY not in shown


def test_the_logs_view_handler_reports_its_own_failure_with_no_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fails() -> None:
        raise RuntimeError("the screen is gone")

    book = LogBook()
    handler = LogBookHandler(book, fails)
    record = logging.LogRecord("a.library", logging.WARNING, __file__, 1, "%s", (_TMDB_KEY,), None)
    TmdbProvider(_http(_answer), api_key=_TMDB_KEY)

    handler.handle(record)

    captured = capsys.readouterr()
    lines = "\n".join(line for _, line in book.lines_after(0))
    for shown in (lines, captured.out, captured.err):
        assert _TMDB_KEY not in shown
