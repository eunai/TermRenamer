"""Render the README's screenshot: a built TV Plan at the Preview Stage, as an SVG.

Run from the repo root::

    uv run python scripts/render_preview.py

It writes ``docs/assets/preview.svg``. The app runs headless at a fixed terminal size,
with static providers in place of TMDB, so the script needs no network, no API key and
no settings file. The source files are empty stand-ins for a person's backups, made in
a temporary folder under folders of fixed names. The footer shows the selected file's
paths cut from the left to fit its width, and each file's path below the temporary
folder (the fixed folders and the file's name) is at least that long, so the temporary
folder's own path, which differs from run to run and names this machine, never reaches
the image. The screen shows no clock, so two runs give the same
file.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.app_bootstrap import Settings
from termrenamer.core.models import EpisodeMetadata
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.stages.preview import footer_path_width
from termrenamer.wiring import PlanningWiring

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "preview.svg"

TERMINAL_SIZE = (120, 36)
BACKUP_FOLDERS = (
    "Backups of my shows and films",
    "Copied from my old hard drives before the move in 2019",
)
"""The folders above the Source, so the footer's paths start inside them."""
SOURCE_FOLDER = "TV Backups"

SHOW = "Breaking Bad"
EPISODES = {
    1: "Pilot",
    2: "Cat's in the Bag...",
    3: "...And the Bag's in the River",
    4: "Cancer Man",
}


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
    folder = parent.joinpath(*BACKUP_FOLDERS, SOURCE_FOLDER)
    folder.mkdir(parents=True)
    for number in EPISODES:
        stem = f"breaking_bad_s01e{number:02d}"
        (folder / f"{stem}.mkv").write_bytes(b"")
        (folder / f"{stem}.srt").write_bytes(b"")
    shortest = min(len(str(path.relative_to(parent))) for path in folder.iterdir())
    if shortest < footer_path_width(TERMINAL_SIZE[0]):
        raise RuntimeError("The fixed folders are too short to keep the temporary path out")
    return folder


async def _screenshot(source: Path) -> str:
    app = TermRenamerApp(wiring=_wiring(), settings=_settings())
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        await pilot.press("f")  # the folder dialog; the folder is chosen in it
        app.screen.dismiss(source)
        await pilot.pause()
        await pilot.press("b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        return app.export_screenshot(title="TermRenamer")


def render_preview(out: Path = DEFAULT_OUT) -> Path:
    """Write the preview screenshot SVG to ``out`` and return ``out``."""
    # The app swaps the root logger's stream handlers for its Logs view on mount;
    # put the caller's handlers back afterwards.
    root_logger = logging.getLogger()
    handlers = list(root_logger.handlers)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            svg = asyncio.run(_screenshot(_make_backups(Path(tmp))))
    finally:
        root_logger.handlers[:] = handlers
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Wrote {render_preview().relative_to(REPO_ROOT)}")
