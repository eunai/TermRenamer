"""Drives the screen in scripted tests: stand-in Providers, the app, keys, and the text on screen.

The stand-ins answer from fixed data and never reach a network. Sources live in each
test's temporary folder. Posters are unavailable unless a test asks for them; then a
stand-in image widget takes the image package's place and a stand-in image host answers
the poster store's downloads.
"""

from __future__ import annotations

import io
import os
import re
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Static
from textual_fspicker import FileOpen, SelectDirectory

from termrenamer.app_bootstrap import Settings, ThemeName
from termrenamer.core.models import Candidate
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.persistence.posters import PosterStore
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.poster_support import ErrorWidget, PosterSupport
from termrenamer.util.http import HttpClient, HttpClientConfig
from termrenamer.wiring import PlanningWiring

from .poster_images import JPEG

SIZE = (120, 36)
"""The design size of the screen."""

SHOW = Candidate(id="11", name="Harbour Lights", year=2019, poster_ref="/hl.jpg")
FERRY = Candidate(id="12", name="Night Ferry", year=2021)
METROPOLIS = Candidate(id="19", name="Metropolis", year=1927)


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data.

    With ``hold`` set, a search after the first waits until the test sets ``go``, so
    the test can look at the screen while the build runs.
    """

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]
    hold: bool = False
    first_done: threading.Event = field(default_factory=threading.Event)
    go: threading.Event = field(default_factory=threading.Event)
    searches: list[str] = field(default_factory=list)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        if self.hold and self.searches:
            self.first_done.set()
            self.go.wait(timeout=10)
        self.searches.append(hint)
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return self.episodes.get((show_id, season, episode))


@dataclass
class FilmStandIn:
    """Answers film searches from fixed data, keyed by (normalised hint, year)."""

    films: dict[tuple[str, int | None], tuple[Candidate, ...]]

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        return self.films.get((hint.casefold().strip(), year), ())


def tv_stand_in(*, hold: bool = False) -> TvStandIn:
    """Harbour Lights (two episodes of season 1) and Night Ferry (one episode)."""
    return TvStandIn(
        shows={"harbour lights": (SHOW,), "night ferry": (FERRY,)},
        episodes={
            ("11", 1, 1): "The Tide Comes In",
            ("11", 1, 2): "Salt and Rope",
            ("12", 1, 1): "Cast Off",
        },
        hold=hold,
    )


def film_stand_in() -> FilmStandIn:
    return FilmStandIn(films={("metropolis", 1927): (METROPOLIS,)})


def wiring(
    *,
    tv: TvStandIn | None = None,
    film: FilmStandIn | None = None,
    tvdb: TvStandIn | None = None,
    omdb: FilmStandIn | None = None,
    tmdb: bool = True,
    posters: PosterStore | None = None,
) -> PlanningWiring:
    """Stand-ins in place of each Provider; ``tmdb=False`` leaves TMDB without a key."""
    return PlanningWiring(
        tv_tmdb=(tv or tv_stand_in()) if tmdb else None,
        tv_tvdb=tvdb,
        film=(film or film_stand_in()) if tmdb else None,
        film_omdb=omdb,
        posters=posters,
    )


def settings(
    *,
    folder_rename: bool = False,
    season_folders: bool = False,
    tv_root: Path | None = None,
    film_root: Path | None = None,
    theme: ThemeName = ThemeName.DARK,
    name_taken: NameTakenPolicy = NameTakenPolicy.SUFFIX,
    show_posters: bool = True,
) -> Settings:
    return Settings(
        tmdb_api_key=None,
        tvdb_api_key=None,
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=1.0,
        http_max_attempts=1,
        http_backoff_base_seconds=0.0,
        http_jitter=False,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=film_root,
        tv_dest_folder=tv_root,
        enable_folder_rename=folder_rename,
        enable_season_folders=season_folders,
        theme=theme,
        name_taken=name_taken,
        show_posters=show_posters,
    )


def make_app(
    wired: PlanningWiring | None = None,
    loaded: Settings | None = None,
    *,
    posters: PosterSupport | None = None,
) -> TermRenamerApp:
    return TermRenamerApp(
        wiring=wired or wiring(), settings=loaded or settings(), poster_support=posters
    )


class StandInImage(Static):
    """Takes the image package's widget's place: writes ``POSTER`` and the file's name."""

    def __init__(self, image: Path, *, on_error: ErrorWidget) -> None:
        super().__init__(f"POSTER {image.name[:8]}")
        self.image: Path | None = image
        self.on_error = on_error


def stand_in_image(path: Path, on_error: ErrorWidget) -> Widget:
    return StandInImage(path, on_error=on_error)


POSTERS_AVAILABLE = PosterSupport(image=stand_in_image)
"""Posters as a terminal that draws images has them, drawn by :class:`StandInImage`."""


class UnreadableImage(StandInImage):
    """As the image package's widget does with a file it cannot read: shows the widget
    ``on_error`` makes, inside itself."""

    def on_mount(self) -> None:
        self.mount(self.on_error(OSError("cannot identify image file")))


POSTERS_UNREADABLE = PosterSupport(
    image=lambda path, on_error: UnreadableImage(path, on_error=on_error)
)
"""Posters available, but every stored file fails to draw."""


@dataclass
class ImageHost:
    """Answers each image download with ``body`` and ``status``; records each request and
    the thread it arrived on."""

    body: bytes = JPEG
    status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)
    gate: threading.Event | None = None
    """When set, each answer waits until the gate opens."""
    attempts: int = 1
    """How many times the store's HTTP client tries a download that gets 429 or 503."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.threads.append(threading.current_thread())
        if self.gate is not None:
            assert self.gate.wait(timeout=5)
        return httpx.Response(
            self.status, headers={"Content-Type": "image/jpeg"}, content=self.body
        )

    @property
    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]

    def store(self, folder: Path) -> PosterStore:
        raw = httpx.Client(transport=httpx.MockTransport(self.handle))
        config = HttpClientConfig(max_attempts=self.attempts, backoff_base_seconds=0, jitter=False)
        return PosterStore(folder, HttpClient(config=config, client=raw))


def tv_backups(parent: Path, name: str = "TV Backups") -> Path:
    """A folder with two Harbour Lights episodes (one with a subtitle), one Night Ferry
    episode, one video whose name cannot be read and a note."""
    folder = parent / name
    folder.mkdir()
    for file_name in (
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Harbour Lights S01E02.mkv",
        "Night Ferry S01E01.mkv",
        "holiday.mkv",
        "notes.txt",
    ):
        (folder / file_name).write_bytes(b"x")
    return folder


def names_in(folder: Path) -> list[str]:
    """Every path under ``folder``, relative and sorted: what is on disk."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def screen_text(app: TermRenamerApp) -> str:
    """The characters on the screen now, the top screen over those under it.

    Each run of spaces is one space, and each line loses its ends' spaces, so tests
    read words rather than columns."""
    lines = screen_lines(app)
    return "\n".join(re.sub(r" {2,}", " ", line).strip() for line in lines)


def screen_lines(app: TermRenamerApp) -> list[str]:
    """The characters on the screen now, one string per row, columns kept."""
    width, height = app.size
    console = Console(
        width=width,
        height=height,
        file=io.StringIO(),
        record=True,
        color_system=None,
        legacy_windows=False,
    )
    console.print(
        app.screen._compositor.render_update(full=True, screen_stack=app._background_screens)
    )
    return console.export_text().splitlines()


def text_of(app: TermRenamerApp, selector: str) -> str:
    """The plain text of one Static on the top screen, unwrapped."""
    widget = app.screen.query_one(selector, Static)
    return str(widget.render().plain)  # type: ignore[union-attr]


def footer_keys(app: TermRenamerApp) -> list[str]:
    """The footer's key hints, as ``key label``."""
    return [f"{key.display} {key.hint}" for key in app.footer_keys()]


async def press(pilot: Pilot[None], *keys: str) -> None:
    await pilot.press(*keys)
    await pilot.pause()


async def until(pilot: Pilot[None], done: Callable[[], bool]) -> None:
    """Let the app run until ``done()`` is true; fail after about five seconds."""
    for _ in range(100):
        if done():
            return
        await pilot.pause(0.05)
    raise AssertionError("waited too long")


async def pick_in_dialog(pilot: Pilot[None], key: str, path: Path | None) -> None:
    """Press ``a`` or ``f``, check the dialog it opens, and choose ``path`` there
    (``None`` presses Escape)."""
    app = pilot.app
    await press(pilot, key)
    assert isinstance(app.screen, FileOpen if key == "a" else SelectDirectory)
    if path is None:
        await press(pilot, "escape")
    else:
        app.screen.dismiss(path)
        await pilot.pause()


def long_season(parent: Path, videos: int) -> tuple[Path, TvStandIn]:
    """A folder with one season of Harbour Lights, ``videos`` episodes long, and the TV
    stand-in that knows each episode."""
    folder = parent / "TV Backups"
    folder.mkdir()
    for episode in range(1, videos + 1):
        (folder / f"Harbour Lights S01E{episode:02d}.mkv").write_bytes(b"x")
    tv = TvStandIn(
        shows={"harbour lights": (SHOW,)},
        episodes={("11", 1, e): f"Episode {e}" for e in range(1, videos + 1)},
    )
    return folder, tv


CELL = "██"
MARK = "▔▔"


def marked_cell(app: TermRenamerApp) -> int | None:
    """Which cell, counted from 1, the selected file's mark is under on screen.

    The count is read from the Title's cells as drawn, the rows scrolled out of view
    included. ``None`` when the mark is not on screen, is under no cell, or the screen
    does not show the row of cells it is under."""
    rows = text_of(app, "#details-cells").splitlines()
    marked = [n for n, row in enumerate(rows) if MARK in row]
    if len(marked) != 1 or marked[0] == 0:
        return None
    column = rows[marked[0]].index(MARK)
    above = rows[marked[0] - 1]
    if above[column : column + len(CELL)] != CELL:
        return None
    # The cells before the mark's row: each line of cells counted on its lowest row,
    # the one with no cell in the row under it.
    before = rows[: marked[0] - 1]
    lowest = [row for n, row in enumerate(before) if CELL in row and CELL not in rows[n + 1]]
    cell = sum(row.count(CELL) for row in lowest) + above[:column].count(CELL) + 1
    lines = screen_lines(app)
    shown = [n for n, line in enumerate(lines) if MARK in line]
    if len(shown) != 1 or shown[0] == 0:
        return None
    left = lines[shown[0]].index(MARK) - column
    if lines[shown[0] - 1][left : left + len(above)] != above:
        return None
    return cell


async def mark_seen_walking(pilot: Pilot[None], videos: int) -> str:
    """Press right to the last file and back to the first, in a Title whose files are
    ``Harbour Lights S01E01.mkv`` on (see :func:`long_season`). After each key, ``y``
    when the footer's ``from`` line names the file now selected and the mark is on
    screen under that file's cell (:func:`marked_cell`); else ``n``."""
    app = pilot.app
    assert isinstance(app, TermRenamerApp)
    seen = []
    walk = list(range(2, videos + 1)) + list(range(videos - 1, 0, -1))
    for episode, key in zip(walk, ["right"] * (videos - 1) + ["left"] * (videos - 1), strict=True):
        await press(pilot, key)
        await pilot.pause()
        source = text_of(app, "#stage-lines").splitlines()[0]
        named = source.startswith("from ") and source.endswith(
            f"Harbour Lights S01E{episode:02d}.mkv"
        )
        seen.append("y" if named and marked_cell(app) == episode else "n")
    return "".join(seen)


async def queue(pilot: Pilot[None], *folders: Path) -> None:
    for folder in folders:
        await pick_in_dialog(pilot, "f", folder)


async def build(pilot: Pilot[None]) -> None:
    await press(pilot, "b")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def lines_with(text: str, needle: str) -> Sequence[str]:
    return [line for line in text.splitlines() if needle in line]


NUL_RESOLVES = ["raises", "as on Windows"]
"""How resolving a path with a NUL character behaves: POSIX raises ``ValueError``;
Windows (CPython 3.13, gh-106242) returns the path as it is unless strict."""


def resolve_nul(monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """Make resolving a path with a NUL character behave ``how`` (one of
    :data:`NUL_RESOLVES`) on this system."""
    if how == "raises":
        if sys.platform == "win32":
            pytest.skip("Windows resolves a path with a NUL character without raising")
        return
    real = os.path.realpath

    def as_on_windows(path: str, *, strict: bool = False) -> str:
        try:
            return real(path, strict=strict)
        except ValueError:
            if strict:
                raise OSError(str(path)) from None
            return os.path.normpath(os.path.abspath(os.fspath(path)))

    monkeypatch.setattr(os.path, "realpath", as_on_windows)
