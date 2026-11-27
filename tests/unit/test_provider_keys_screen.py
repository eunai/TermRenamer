"""The screen with some Provider keys missing: choice of Provider, "no key", and Build."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Label, RichLog, TabbedContent

from termrenamer.api.omdb import StaticOmdbFilmMetadataProvider
from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata, PlanEntryStatus, ScanMode
from termrenamer.tui.app import TermRenamerApp
from termrenamer.wiring import PlanningWiring

_SIZE = (120, 40)


def _tv() -> StaticTvMetadataProvider:
    return StaticTvMetadataProvider(
        _mapping={("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="E1")},
    )


def _film() -> StaticFilmMetadataProvider:
    return StaticFilmMetadataProvider(
        _mapping={("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999)},
    )


def _omdb() -> StaticOmdbFilmMetadataProvider:
    return StaticOmdbFilmMetadataProvider(
        _mapping={("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999)},
    )


def _wiring(*, tmdb: bool = False, tvdb: bool = False, omdb: bool = False) -> PlanningWiring:
    return PlanningWiring(
        tv_tmdb=_tv() if tmdb else None,
        tv_tvdb=_tv() if tvdb else None,
        film=_film() if tmdb else None,
        film_omdb=_omdb() if omdb else None,
    )


def _label(app: TermRenamerApp, provider_id: str) -> str:
    return str(app.query_one(f"#provider-{provider_id}-label", Label).content)


def _log_text(app: TermRenamerApp) -> str:
    return "\n".join(strip.text for strip in app.query_one("#log_panel", RichLog).lines)


async def _build(app: TermRenamerApp, pilot: object) -> None:
    from textual.pilot import Pilot

    assert isinstance(pilot, Pilot)
    await pilot.press("b")
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
async def test_with_only_a_tvdb_key_a_tv_plan_is_built_with_thetvdb(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring(tvdb=True))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        assert app.scan_mode is ScanMode.TV
        assert app.provider_id == "tvdb"
        assert "no key" in _label(app, "tmdb")
        assert "no key" not in _label(app, "tvdb")

        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await _build(app, pilot)

        assert app.current_plan is not None
        assert [e.status for e in app.current_plan.entries] == [PlanEntryStatus.MATCHED]


@pytest.mark.asyncio
async def test_with_only_an_omdb_key_a_film_plan_is_built_with_omdb(tmp_path: Path) -> None:
    (tmp_path / "The.Matrix.1999.1080p.mkv").write_bytes(b"v")
    app = TermRenamerApp(wiring=_wiring(omdb=True))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        # No TV Provider has a key: TV starts on TMDB, marked "no key".
        assert app.provider_id == "tmdb"
        assert "no key" in _label(app, "tmdb")

        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
        assert app.provider_id == "omdb"
        assert "no key" not in _label(app, "omdb")

        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await _build(app, pilot)

        assert app.current_plan is not None
        assert [e.status for e in app.current_plan.entries] == [PlanEntryStatus.MATCHED]


@pytest.mark.parametrize(
    ("keys", "tv_provider", "film_provider"),
    [
        ({"tmdb": True, "tvdb": True, "omdb": True}, "tmdb", "tmdb"),
        ({"tvdb": True, "omdb": True}, "tvdb", "omdb"),
        ({"tmdb": True}, "tmdb", "tmdb"),
        ({"tvdb": True}, "tvdb", "tmdb"),
    ],
)
@pytest.mark.asyncio
async def test_every_change_of_mode_picks_the_first_provider_with_a_key(
    keys: dict[str, bool], tv_provider: str, film_provider: str
) -> None:
    app = TermRenamerApp(wiring=_wiring(**keys))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        assert app.provider_id == tv_provider
        # Step away from the chosen Provider, so the Mode change has to choose again.
        await pilot.press("p")
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
        assert app.provider_id == film_provider

        await pilot.press("p")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.TV
        assert app.provider_id == tv_provider


@pytest.mark.asyncio
async def test_the_provider_key_steps_through_every_provider_of_the_mode() -> None:
    app = TermRenamerApp(wiring=_wiring(tvdb=True))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        seen = [app.provider_id]
        for _ in range(2):
            await pilot.press("p")
            await pilot.pause()
            seen.append(app.provider_id)
        assert seen == ["tvdb", "tmdb", "tvdb"]

        await pilot.press("m")
        await pilot.pause()
        seen = [app.provider_id]
        for _ in range(2):
            await pilot.press("p")
            await pilot.pause()
            seen.append(app.provider_id)
        assert seen == ["tmdb", "omdb", "tmdb"]
        assert "no key" in _label(app, "tmdb")
        assert "no key" in _label(app, "omdb")


@pytest.mark.asyncio
async def test_with_every_key_no_provider_is_marked_no_key() -> None:
    app = TermRenamerApp(wiring=_wiring(tmdb=True, tvdb=True, omdb=True))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        for provider_id in ("tmdb", "tvdb", "omdb"):
            assert "no key" not in _label(app, provider_id)


@pytest.mark.parametrize(
    ("keys", "mode_presses", "provider_presses", "file_name", "message", "variable"),
    [
        (
            {"omdb": True},
            0,
            0,
            "Show.Name.S01E01.mkv",
            "TMDB requires an API key",
            "TERMRENAMER_TMDB_API_KEY",
        ),
        (
            {"tvdb": True},
            1,
            0,
            "The.Matrix.1999.1080p.mkv",
            "TMDB requires an API key",
            "TERMRENAMER_TMDB_API_KEY",
        ),
        (
            {"tmdb": True},
            0,
            1,
            "Show.Name.S01E01.mkv",
            "TheTVDB requires an API key",
            "TERMRENAMER_TVDB_API_KEY",
        ),
        (
            {"tmdb": True},
            1,
            1,
            "The.Matrix.1999.1080p.mkv",
            "OMDb requires an API key",
            "TERMRENAMER_OMDB_API_KEY",
        ),
    ],
)
@pytest.mark.asyncio
async def test_building_with_a_provider_that_has_no_key_gives_its_message_and_no_plan(
    tmp_path: Path,
    keys: dict[str, bool],
    mode_presses: int,
    provider_presses: int,
    file_name: str,
    message: str,
    variable: str,
) -> None:
    (tmp_path / file_name).write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring(**keys))
    async with app.run_test(size=_SIZE) as pilot:
        app.query_one("#bottom-tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        for _ in range(mode_presses):
            await pilot.press("m")
            await pilot.pause()
        for _ in range(provider_presses):
            await pilot.press("p")
            await pilot.pause()
        assert "no key" in _label(app, app.provider_id)

        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await _build(app, pilot)

        assert app.current_plan is None
        text = _log_text(app)
        assert message in text
        assert variable in text
