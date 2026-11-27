"""Drives the screen in scripted tests: stand-in Providers, the app, keys, and the text on screen.

The stand-ins answer from fixed data and never reach a network. Sources live in each
test's temporary folder.
"""

from __future__ import annotations

import io
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from textual.pilot import Pilot
from textual.widgets import Static
from textual_fspicker import FileOpen, SelectDirectory
from textual_fspicker.parts import DirectoryNavigation

from termrenamer.app_bootstrap import Settings, ThemeName
from termrenamer.core.models import Candidate
from termrenamer.tui.app import TermRenamerApp
from termrenamer.wiring import PlanningWiring

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
) -> PlanningWiring:
    """Stand-ins in place of each Provider; ``tmdb=False`` leaves TMDB without a key."""
    return PlanningWiring(
        tv_tmdb=(tv or tv_stand_in()) if tmdb else None,
        tv_tvdb=tvdb,
        film=(film or film_stand_in()) if tmdb else None,
        film_omdb=omdb,
    )


def settings(
    *,
    folder_rename: bool = False,
    season_folders: bool = False,
    tv_root: Path | None = None,
    film_root: Path | None = None,
    theme: ThemeName = ThemeName.DARK,
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
    )


def make_app(wired: PlanningWiring | None = None, loaded: Settings | None = None) -> TermRenamerApp:
    return TermRenamerApp(wiring=wired or wiring(), settings=loaded or settings())


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
    lines = console.export_text().splitlines()
    return "\n".join(re.sub(r" {2,}", " ", line).strip() for line in lines)


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


async def wait_for_listing(pilot: Pilot[None]) -> None:
    """Wait until the open file or folder dialog has listed its folder.

    The dialog lists it in a worker that may not have started yet, and closing the
    dialog under that worker fails it; so wait for the entries, then the worker.
    """
    listing = pilot.app.screen.query_one(DirectoryNavigation)
    for _ in range(500):
        if listing.option_count:
            break
        await pilot.pause(0.01)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def pick_in_dialog(pilot: Pilot[None], key: str, path: Path | None) -> None:
    """Press ``a`` or ``f``, check the dialog it opens, and choose ``path`` there
    (``None`` presses Escape)."""
    app = pilot.app
    await press(pilot, key)
    assert isinstance(app.screen, FileOpen if key == "a" else SelectDirectory)
    await wait_for_listing(pilot)
    if path is None:
        await press(pilot, "escape")
    else:
        app.screen.dismiss(path)
        await pilot.pause()


async def queue(pilot: Pilot[None], *folders: Path) -> None:
    for folder in folders:
        await pick_in_dialog(pilot, "f", folder)


async def build(pilot: Pilot[None]) -> None:
    await press(pilot, "b")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def lines_with(text: str, needle: str) -> Sequence[str]:
    return [line for line in text.splitlines() if needle in line]
