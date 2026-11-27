"""No Provider key shows on the screen, even when the Provider's own error quotes it.

A Provider that echoes the key of a request in its error text (OMDb's "Invalid API key"
answers can) has its message shown on the footer after Build and in the Match picker
after a typed search. Each registered key and token is masked in the Provider's message
itself, so every place the message reaches shows ``***``. OMDb is a real
:class:`OmdbProvider` talking to a stand-in transport with a made-up key; no request
leaves the machine.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from termrenamer.api.omdb import OmdbProvider
from termrenamer.tui.dialogs.match_picker import MatchPicker
from termrenamer.tui.stage import Stage
from termrenamer.util.http import HttpClient, HttpClientConfig

from .screen_driver import SIZE, build, make_app, press, queue, screen_text, text_of, wiring

_OMDB_KEY = "made-up-omdb-key-for-the-screen"


def _omdb(answer: httpx.MockTransport) -> OmdbProvider:
    config = HttpClientConfig(max_attempts=1, backoff_base_seconds=0.0, jitter=False)
    http = HttpClient(config=config, client=httpx.Client(transport=answer))
    return OmdbProvider(http, api_key=_OMDB_KEY)


def _echoing_the_key(found: set[str]) -> httpx.MockTransport:
    """Metropolis (1927) for each title in ``found``; for any other, an error that
    quotes the request's key, as a server that echoes its input does."""

    def answer(request: httpx.Request) -> httpx.Response:
        title = request.url.params.get("s") or request.url.params.get("t") or ""
        if title in found:
            film = {"Title": "Metropolis", "Year": "1927", "imdbID": "tt0017136"}
            return httpx.Response(200, json={"Response": "True", "Search": [film]})
        key = request.url.params.get("apikey")
        return httpx.Response(200, json={"Response": "False", "Error": f"Invalid key {key}."})

    return httpx.MockTransport(answer)


def _film_backups(parent: Path) -> Path:
    folder = parent / "Film Backups"
    folder.mkdir()
    (folder / "Metropolis (1927).mkv").write_bytes(b"x")
    return folder.resolve()


async def test_a_provider_error_that_quotes_the_key_shows_it_masked_after_build(
    tmp_path: Path,
) -> None:
    folder = _film_backups(tmp_path)
    app = make_app(wiring(omdb=_omdb(_echoing_the_key(set()))))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m", "p")  # Film, then OMDb
        await queue(pilot, folder)
        await build(pilot)
        stage = app.stage
        message = text_of(app, "#message")
        text = screen_text(app)

    assert stage is Stage.QUEUE
    assert "OMDb: Invalid key ***." in message
    assert _OMDB_KEY not in text


async def test_a_provider_error_that_quotes_the_key_shows_it_masked_in_the_match_picker(
    tmp_path: Path,
) -> None:
    folder = _film_backups(tmp_path)
    app = make_app(wiring(omdb=_omdb(_echoing_the_key({"Metropolis"}))))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m", "p")
        await queue(pilot, folder)
        await build(pilot)
        assert app.stage is Stage.PREVIEW
        await press(pilot, "down", "t")
        assert isinstance(app.screen, MatchPicker)
        await press(pilot, "slash", *"Nosferatu", "enter")
        await app.screen.workers.wait_for_complete()
        await pilot.pause()
        text = screen_text(app)

    assert "OMDb: Invalid key ***. Nothing changed." in text
    assert _OMDB_KEY not in text
