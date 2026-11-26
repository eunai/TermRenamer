"""Render the README's screenshot: a built TV plan in the preview, as an SVG.

Run from the repo root::

    uv run python scripts/render_preview.py

It writes ``docs/assets/preview.svg``. The app runs headless at a fixed terminal size,
with static providers in place of TMDB, so the script needs no network, no API key and
no settings file. The source files are empty stand-ins for the owner's backups, made in
a temporary folder; the preview shows paths relative to that folder, so no path from
this machine reaches the image. The clock and the Activity timestamps are pinned, so two
runs give the same file.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from textual.widgets._header import HeaderClock

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.app_bootstrap import Settings
from termrenamer.core.models import EpisodeMetadata
from termrenamer.tui.app import TermRenamerApp
from termrenamer.wiring import PlanningWiring

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "preview.svg"

TERMINAL_SIZE = (120, 46)
SOURCE_FOLDER = "TV Backups"
SHOW = "Breaking Bad"
EPISODES = {
    1: "Pilot",
    2: "Cat's in the Bag...",
    3: "...And the Bag's in the River",
    4: "Cancer Man",
}
FIXED_NOW = datetime(2026, 1, 20, 9, 41, 0)


class _FixedDatetime(datetime):
    """``datetime`` whose ``now()`` is pinned, for the Activity tab's timestamps."""

    @classmethod
    def now(cls, tz: object = None) -> _FixedDatetime:
        return cls.fromtimestamp(FIXED_NOW.timestamp())


def _wiring() -> PlanningWiring:
    tv = StaticTvMetadataProvider(
        _mapping={
            (SHOW.casefold(), 1, number): EpisodeMetadata(show_title=SHOW, episode_title=title)
            for number, title in EPISODES.items()
        },
    )
    film = StaticFilmMetadataProvider(_mapping={})
    return PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)


def _settings() -> Settings:
    """Folder rename and season folders on; no keys, no destination root."""
    return Settings(
        tmdb_api_key=None,
        tvdb_api_key=None,
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=10.0,
        http_max_attempts=1,
        http_backoff_base_seconds=0.0,
        http_jitter=False,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=None,
        enable_folder_rename=True,
        enable_season_folders=True,
    )


def _make_backups(parent: Path) -> Path:
    folder = parent / SOURCE_FOLDER
    folder.mkdir()
    for number in EPISODES:
        stem = f"breaking_bad_s01e{number:02d}"
        (folder / f"{stem}.mkv").write_bytes(b"")
        (folder / f"{stem}.srt").write_bytes(b"")
    return folder


async def _screenshot(source: Path) -> str:
    app = TermRenamerApp(wiring=_wiring(), settings=_settings())
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        app.query_one(HeaderClock).time_format = FIXED_NOW.strftime("%H:%M:%S")
        app._on_folder_picked(source)
        await pilot.pause()
        with mock.patch("termrenamer.core.planning.datetime", _FixedDatetime):
            await pilot.press("b")
            await app.workers.wait_for_complete()
            await pilot.pause()
        await pilot.pause()
        return app.export_screenshot(title="TermRenamer")


def render_preview(out: Path = DEFAULT_OUT) -> Path:
    """Write the preview screenshot SVG to ``out`` and return ``out``."""
    with tempfile.TemporaryDirectory() as tmp:
        svg = asyncio.run(_screenshot(_make_backups(Path(tmp))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Wrote {render_preview().relative_to(REPO_ROOT)}")
