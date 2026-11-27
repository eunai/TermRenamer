"""The poster store: a Poster reference becomes a local image file, kept for 30 days.

Driven through the store's interface with a stand-in HTTP transport, a temporary folder
and a clock the test controls. No test reaches a network or the real cache folder.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from termrenamer.persistence.posters import (
    MAX_POSTER_BYTES,
    PosterError,
    PosterRequest,
    PosterStore,
    poster_folder,
)
from termrenamer.util.http import HttpClient, HttpClientConfig

from .links import point_folder_at
from .poster_images import BROKEN_JPEG, JPEG, PNG, WEBP

if TYPE_CHECKING:
    from conftest import IsolatedDirs

DAY = 24 * 60 * 60.0
TMDB = PosterRequest(provider_id="tmdb", ref="/harbour-lights-2011.jpg")
TVDB = PosterRequest(
    provider_id="tvdb", ref="https://artworks.thetvdb.com/banners/posters/81001-1.jpg"
)


@dataclass
class Clock:
    """A clock the test moves by hand."""

    now: float = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class ImageHost:
    """Answers every request with ``body``; records each request it was sent."""

    body: bytes = JPEG
    status: int = 200
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "image/jpeg"})
    requests: list[httpx.Request] = field(default_factory=list)
    fail: Callable[[httpx.Request], None] | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            self.fail(request)
        return httpx.Response(self.status, headers=self.headers, content=self.body)


def store_for(
    host: ImageHost, folder: Path, clock: Clock, *, inside: Path | None = None
) -> PosterStore:
    raw = httpx.Client(transport=httpx.MockTransport(host.handle))
    http = HttpClient(config=HttpClientConfig(max_attempts=2, backoff_base_seconds=0), client=raw)
    return PosterStore(folder, http, clock=clock, inside=inside)


def files_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def test_a_poster_is_downloaded_once_and_reused_while_young(tmp_path: Path) -> None:
    host, clock = ImageHost(), Clock()
    store = store_for(host, tmp_path / "posters", clock)

    first = store.fetch(TMDB)
    clock.now += 29 * DAY
    again = store.fetch(TMDB)

    assert len(host.requests) == 1
    assert first == again
    assert first.read_bytes() == JPEG
    assert store.stored(TMDB) == first


def test_tmdb_posters_come_from_its_image_host_at_a_fixed_size(tmp_path: Path) -> None:
    host = ImageHost()
    store_for(host, tmp_path, Clock()).fetch(TMDB)

    assert str(host.requests[0].url) == "https://image.tmdb.org/t/p/w342/harbour-lights-2011.jpg"


def test_thetvdb_posters_come_from_the_address_given(tmp_path: Path) -> None:
    host = ImageHost()
    store_for(host, tmp_path, Clock()).fetch(TVDB)

    assert str(host.requests[0].url) == TVDB.ref


@pytest.mark.parametrize("request_", [TMDB, TVDB])
def test_the_image_request_carries_no_key_and_no_personal_detail(
    request_: PosterRequest, tmp_path: Path
) -> None:
    host = ImageHost()
    store_for(host, tmp_path, Clock()).fetch(request_)

    sent = host.requests[0]
    assert sent.method == "GET"
    assert sent.url.query == b""
    assert {name.lower() for name in sent.headers} <= {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
    }
    assert sent.headers["user-agent"].startswith("python-httpx/")


def test_a_file_older_than_30_days_is_downloaded_again(tmp_path: Path) -> None:
    host, clock = ImageHost(), Clock()
    store = store_for(host, tmp_path, clock)
    store.fetch(TMDB)

    clock.now += 31 * DAY
    assert store.stored(TMDB) is None
    store.fetch(TMDB)

    assert len(host.requests) == 2


def test_old_files_are_deleted_at_start_and_young_ones_and_other_files_kept(
    tmp_path: Path,
) -> None:
    host, clock = ImageHost(), Clock()
    store = store_for(host, tmp_path, clock)
    old = store.fetch(TMDB)
    clock.now += 20 * DAY
    young = store.fetch(TVDB)
    other = tmp_path / "notes.txt"
    other.write_text("kept")
    os.utime(other, (0, 0))

    clock.now += 11 * DAY
    count = store.remove_old()

    assert count == 1
    assert not old.exists()
    assert young.exists()
    assert other.exists()


def test_removing_old_files_from_a_missing_folder_does_nothing(tmp_path: Path) -> None:
    store = store_for(ImageHost(), tmp_path / "never-made", Clock())

    assert store.remove_old() == 0
    assert not (tmp_path / "never-made").exists()


def test_each_file_is_named_by_a_hash_inside_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "posters"
    path = store_for(ImageHost(), folder, Clock()).fetch(TVDB)

    assert path.parent == folder
    assert files_in(tmp_path) == [path]
    stem, suffix = path.name.split(".")
    assert len(stem) == 64 and set(stem) <= set("0123456789abcdef")
    assert "81001" not in path.name


@pytest.mark.parametrize(
    "request_",
    [
        PosterRequest("tmdb", "https://image.tmdb.org/t/p/w342/x.jpg"),
        PosterRequest("tmdb", "/../../etc/passwd.jpg"),
        PosterRequest("tmdb", "/a/b.jpg"),
        PosterRequest("tmdb", "/poster.exe"),
        PosterRequest("tmdb", ""),
        PosterRequest("tvdb", "http://artworks.thetvdb.com/banners/posters/1.jpg"),
        PosterRequest("tvdb", "https://example.com/banners/posters/1.jpg"),
        PosterRequest("tvdb", "https://artworks.thetvdb.com.example.com/1.jpg"),
        PosterRequest("tvdb", "https://user:pw@artworks.thetvdb.com/1.jpg"),
        PosterRequest("tvdb", "https://artworks.thetvdb.com:8443/1.jpg"),
        PosterRequest("tvdb", "https://artworks.thetvdb.com/"),
        PosterRequest("tvdb", "/banners/posters/1.jpg"),
        PosterRequest("omdb", "https://m.media-amazon.com/images/x.jpg"),
    ],
)
def test_a_reference_off_the_expected_hosts_is_refused_without_a_request(
    request_: PosterRequest, tmp_path: Path
) -> None:
    host = ImageHost()
    store = store_for(host, tmp_path, Clock())

    with pytest.raises(PosterError):
        store.fetch(request_)

    assert host.requests == []
    assert store.stored(request_) is None
    assert files_in(tmp_path) == []


def test_a_file_larger_than_the_limit_is_refused(tmp_path: Path) -> None:
    host = ImageHost(body=JPEG + b"\x00" * MAX_POSTER_BYTES)

    with pytest.raises(PosterError, match="larger"):
        store_for(host, tmp_path, Clock()).fetch(TMDB)

    assert files_in(tmp_path) == []


def test_a_file_larger_than_the_limit_is_refused_while_it_streams(tmp_path: Path) -> None:
    """With no length given ahead, the read stops past the limit."""

    def chunks() -> httpx.SyncByteStream:
        class Stream(httpx.SyncByteStream):
            def __iter__(self):  # type: ignore[no-untyped-def]
                yield JPEG
                for _ in range(MAX_POSTER_BYTES // 65536 + 2):
                    yield b"\x00" * 65536

        return Stream()

    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, stream=chunks())

    raw = httpx.Client(transport=httpx.MockTransport(handle))
    store = PosterStore(tmp_path, HttpClient(client=raw), clock=Clock())

    with pytest.raises(PosterError, match="larger"):
        store.fetch(TMDB)

    assert files_in(tmp_path) == []


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"<html>not found</html>", "image/jpeg"),
        (JPEG, "text/html"),
        (b"", "image/jpeg"),
    ],
)
def test_a_body_that_is_not_an_image_is_refused(
    body: bytes, content_type: str, tmp_path: Path
) -> None:
    host = ImageHost(body=body, headers={"Content-Type": content_type})

    with pytest.raises(PosterError, match="not an image"):
        store_for(host, tmp_path, Clock()).fetch(TMDB)

    assert files_in(tmp_path) == []


def test_png_and_webp_images_are_accepted(tmp_path: Path) -> None:
    for body, request_ in ((PNG, TMDB), (WEBP, TVDB)):
        path = store_for(ImageHost(body=body), tmp_path, Clock()).fetch(request_)
        assert path.read_bytes() == body


@pytest.mark.parametrize("status", [404, 500, 301])
def test_a_failed_download_is_a_poster_error_and_stores_nothing(
    status: int, tmp_path: Path
) -> None:
    host = ImageHost(status=status, headers={"Location": "https://example.com/x.jpg"})

    with pytest.raises(PosterError, match="download failed"):
        store_for(host, tmp_path, Clock()).fetch(TMDB)

    assert len(host.requests) == 1
    assert files_in(tmp_path) == []


def test_a_network_failure_is_a_poster_error(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> None:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(PosterError, match="download failed"):
        store_for(ImageHost(fail=refuse), tmp_path, Clock()).fetch(TMDB)

    assert files_in(tmp_path) == []


def test_a_download_error_quotes_no_address_from_the_error_text(tmp_path: Path) -> None:
    # The error is logged as "No Poster for ...: <message>"; an error a library raises
    # may quote an address with a query, which never reaches the message.
    def broken(request: httpx.Request) -> None:
        raise httpx.RemoteProtocolError(
            "peer closed https://image.tmdb.org/x.jpg?api_key=secretvalue", request=request
        )

    with pytest.raises(PosterError) as raised:
        store_for(ImageHost(fail=broken), tmp_path, Clock()).fetch(TMDB)

    assert str(raised.value) == "download failed: RemoteProtocolError"


@pytest.mark.parametrize(
    ("platform", "variable", "folder"),
    [
        ("win32", "LOCALAPPDATA", "local_appdata"),
        ("linux", "XDG_CACHE_HOME", "cache_home"),
        ("darwin", "XDG_CACHE_HOME", "cache_home"),
    ],
)
def test_the_poster_folder_is_under_the_per_user_cache_folder(
    platform: str,
    variable: str,
    folder: str,
    isolated_settings_dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    base: Path = getattr(isolated_settings_dirs, folder)

    assert poster_folder() == base / "termrenamer" / "posters"


@pytest.mark.parametrize(
    ("platform", "variable", "value", "fallback"),
    [
        ("win32", "LOCALAPPDATA", "", ("AppData", "Local")),
        ("linux", "XDG_CACHE_HOME", "", (".cache",)),
        ("darwin", "XDG_CACHE_HOME", "relative/cache", (".cache",)),
    ],
)
def test_the_poster_folder_falls_back_to_the_home_folder(
    platform: str,
    variable: str,
    value: str,
    fallback: tuple[str, ...],
    isolated_settings_dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(variable, value)

    expected = Path.home().joinpath(*fallback, "termrenamer", "posters")
    assert poster_folder() == expected
    assert Path.home() == isolated_settings_dirs.home


def test_the_app_deletes_old_poster_files_at_start(tmp_path: Path) -> None:
    from unittest import mock

    from termrenamer import __main__ as main_mod
    from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
    from termrenamer.tui.poster_support import PosterSupport
    from termrenamer.wiring import PlanningWiring

    host, clock = ImageHost(), Clock()
    store = store_for(host, tmp_path, clock)
    old = store.fetch(TMDB)
    clock.now += 31 * DAY
    wired = PlanningWiring(
        tv_tmdb=StaticTvMetadataProvider(_mapping={}),
        tv_tvdb=None,
        film=StaticFilmMetadataProvider(_mapping={}),
        film_omdb=None,
        posters=store,
    )

    with (
        mock.patch("termrenamer.wiring.bootstrap_wiring", return_value=(None, wired)),
        mock.patch(
            "termrenamer.tui.poster_support.detect_poster_support", return_value=PosterSupport()
        ),
        mock.patch("termrenamer.tui.app.TermRenamerApp.run"),
    ):
        main_mod.main()

    assert not old.exists()


def test_the_wiring_keeps_posters_in_the_per_user_folder(
    isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.wiring import bootstrap_wiring

    monkeypatch.setenv("TERMRENAMER_OMDB_API_KEY", "k")
    _settings, wired = bootstrap_wiring()

    assert wired.posters is not None
    assert wired.posters.folder == poster_folder()
    assert not wired.posters.folder.exists()


def test_with_pillow_a_body_that_cannot_be_decoded_is_refused(tmp_path: Path) -> None:
    pytest.importorskip("PIL.Image")
    host = ImageHost(body=BROKEN_JPEG)

    with pytest.raises(PosterError, match="not an image"):
        store_for(host, tmp_path, Clock()).fetch(TMDB)

    assert files_in(tmp_path) == []


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="needs POSIX folder permissions, which root ignores",
)
def test_a_folder_the_store_cannot_search_is_a_poster_error_never_a_crash(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "posters"
    store = store_for(ImageHost(), folder, Clock())
    store.fetch(TMDB)
    folder.chmod(0o600)  # readable, but its files cannot be reached
    try:
        stored = store.stored(TMDB)
        removed = store.remove_old()
        with pytest.raises(PosterError):
            store.fetch(TVDB)
    finally:
        folder.chmod(0o700)

    assert stored is None
    assert removed == 0


def elsewhere_with_posters(folder: Path, clock: Clock) -> tuple[Path, Path]:
    """``folder`` with a young stored Poster (TMDB's) and an old one, as a store left
    them; the old one's path is returned too."""
    young = store_for(ImageHost(), folder, clock).fetch(TMDB)
    old = folder / ("0" * 64 + ".poster")
    old.write_bytes(JPEG)
    os.utime(old, (clock.now - 31 * DAY, clock.now - 31 * DAY))
    return young, old


def poster_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "poster folder" in r.getMessage()]


@pytest.mark.parametrize(
    ("linked", "outside"), [("posters", True), ("termrenamer", True), ("termrenamer", False)]
)
def test_a_poster_folder_reached_through_a_link_is_never_read_or_written(
    tmp_path: Path, linked: str, outside: bool, caplog: pytest.LogCaptureFixture
) -> None:
    # Either the posters folder or the termrenamer folder holding it is a link to a
    # folder, outside the cache folder or inside it, where a store's files already are.
    clock = Clock()
    cache = tmp_path / "cache"
    elsewhere = tmp_path / "elsewhere" if outside else cache / "elsewhere"
    link = cache / "termrenamer" / "posters" if linked == "posters" else cache / "termrenamer"
    link.parent.mkdir(parents=True)
    target = elsewhere if linked == "posters" else elsewhere / "posters"
    target.mkdir(parents=True)
    young, old = elsewhere_with_posters(target, clock)
    point_folder_at(link, elsewhere)
    before = files_in(elsewhere)
    host = ImageHost()
    store = store_for(host, cache / "termrenamer" / "posters", clock, inside=cache)

    stored = store.stored(TMDB)
    with pytest.raises(PosterError):
        store.fetch(TVDB)
    removed = store.remove_old()

    assert stored is None
    assert removed == 0 and old.exists() and young.exists()
    assert host.requests == []
    assert files_in(elsewhere) == before
    assert len(poster_lines(caplog)) == 1


def test_the_wiring_keeps_the_poster_folder_inside_the_cache_folder(
    isolated_settings_dirs: IsolatedDirs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.wiring import bootstrap_wiring

    monkeypatch.setenv("TERMRENAMER_OMDB_API_KEY", "k")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "posters").mkdir(parents=True)
    elsewhere_with_posters(elsewhere / "posters", Clock(now=time.time()))
    cache = poster_folder().parent.parent
    cache.mkdir(parents=True, exist_ok=True)
    point_folder_at(cache / "termrenamer", elsewhere)
    _settings, wired = bootstrap_wiring()

    assert wired.posters is not None
    assert wired.posters.stored(TMDB) is None  # read from disk only; nothing is sent
