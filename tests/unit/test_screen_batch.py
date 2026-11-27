"""Today's screen on the core seam: the queue, the settings owner and the Plan's life."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, RichLog, TabbedContent

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.app_bootstrap import Settings
from termrenamer.core.models import ApplyResult, Candidate, EpisodeMetadata, Plan, ScanMode
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.screens import SettingsScreen
from termrenamer.wiring import PlanningWiring

if TYPE_CHECKING:
    from conftest import IsolatedDirs

_SIZE = (120, 40)


def _tv() -> StaticTvMetadataProvider:
    return StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )


def _wiring(tv: object | None = None) -> PlanningWiring:
    return PlanningWiring(
        tv_tmdb=tv if tv is not None else _tv(),  # type: ignore[arg-type]
        tv_tvdb=_tv(),
        film=StaticFilmMetadataProvider(_mapping={}),
        film_omdb=None,
    )


def _settings(tmp_path: Path, *, folder_rename: bool = True) -> Settings:
    return Settings(
        tmdb_api_key="k",
        tvdb_api_key="k",
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=30.0,
        http_max_attempts=4,
        http_backoff_base_seconds=0.5,
        http_jitter=True,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=tmp_path / "tv",
        enable_folder_rename=folder_rename,
        enable_season_folders=True,
    )


def _log_text(app: TermRenamerApp) -> str:
    return "\n".join(strip.text for strip in app.query_one("#log_panel", RichLog).lines)


async def _show_logs(app: TermRenamerApp, pilot: Pilot[None]) -> None:
    app.query_one("#bottom-tabs", TabbedContent).active = "tab-logs"
    await pilot.pause()


async def _build(app: TermRenamerApp, pilot: Pilot[None]) -> None:
    await pilot.press("b")
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
async def test_a_source_already_queued_is_refused_with_a_message(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(folder)
        app._on_folder_picked(folder)
        app._on_folder_picked(tmp_path / "BACKUPS")
        await pilot.pause()

        assert app.queue.sources == (folder.resolve(),)
        assert _log_text(app).count("Already queued") == 2


@pytest.mark.asyncio
async def test_a_plan_setting_changed_in_settings_discards_the_plan_and_keeps_the_queue(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path))
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(tmp_path)
        await _build(app, pilot)
        assert app.current_plan is not None

        screen = SettingsScreen()
        app.push_screen(screen)
        await pilot.pause()
        tv_input = app.screen.query_one("#tv-destination-input", Input)
        screen.on_input_submitted(Input.Submitted(tv_input, str(tmp_path / "elsewhere")))
        await pilot.pause()

        assert app.current_plan is None
        assert app.queue.sources == (tmp_path.resolve(),)
        assert app.session_settings.destination_root(ScanMode.TV) == tmp_path / "elsewhere"
        assert "Plan discarded" in _log_text(app)


@pytest.mark.parametrize("key", ["m", "p"])
@pytest.mark.asyncio
async def test_a_mode_or_provider_change_discards_the_plan_with_a_message(
    tmp_path: Path, key: str
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(tmp_path)
        await _build(app, pilot)
        assert app.current_plan is not None

        await pilot.press(key)
        await pilot.pause()

        assert app.current_plan is None
        assert app.queue.sources == (tmp_path.resolve(),)
        assert "Plan discarded" in _log_text(app)


@pytest.mark.asyncio
async def test_after_apply_no_plan_exists_and_a_settings_change_discards_nothing(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path, folder_rename=False))
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(tmp_path)
        await _build(app, pilot)
        app._apply_current_plan()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.current_plan is None
        assert (tmp_path / "Show Name - S01E01 - Pilot.mkv").is_file()

        await pilot.press("m")
        await pilot.pause()

        assert app.scan_mode is ScanMode.FILM
        assert "Plan discarded" not in _log_text(app)


class _BlockingTv:
    """A TV stand-in whose search waits until the test lets it answer."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.started.set()
        self.release.wait(timeout=10)
        return (Candidate(id="show name", name="Show Name", year=None),)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return "Pilot"


@pytest.mark.asyncio
async def test_settings_mode_and_provider_cannot_change_while_a_plan_is_built(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    blocking = _BlockingTv()
    app = TermRenamerApp(wiring=_wiring(blocking), settings=_settings(tmp_path))
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(tmp_path)
        await pilot.press("b")
        assert blocking.started.wait(timeout=10)
        try:
            for key in ("m", "p", "ctrl+comma"):
                await pilot.press(key)
                await pilot.pause()
            assert app.scan_mode is ScanMode.TV
            assert app.provider_id == "tmdb"
            assert not isinstance(app.screen, SettingsScreen)
            assert _log_text(app).count("cannot change while a Plan is being built") == 3
        finally:
            blocking.release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.current_plan is not None
        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM


@pytest.mark.asyncio
async def test_the_settings_screen_reads_and_writes_through_the_settings_owner(
    tmp_path: Path, isolated_settings_dirs: IsolatedDirs
) -> None:
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path, folder_rename=False))
    async with app.run_test(size=_SIZE) as pilot:
        await pilot.pause()
        app.session_settings.set_destination_root(ScanMode.FILM, tmp_path / "films")
        screen = SettingsScreen()
        app.push_screen(screen)
        await pilot.pause()

        assert app.screen.query_one("#film-destination-input", Input).value == str(
            tmp_path / "films"
        )
        assert app.screen.query_one("#tv-destination-input", Input).value == str(tmp_path / "tv")
        screen._persist_layout(True, True)  # noqa: SLF001
        await pilot.pause()

        assert app.session_settings.folder_rename is True
        assert app.session_settings.season_folders is True
        assert sorted(p.name for p in tmp_path.iterdir()) == []
        assert not isolated_settings_dirs.user_settings_file.exists()


@pytest.mark.asyncio
async def test_a_destination_root_is_ignored_while_folder_rename_is_off(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path, folder_rename=False))
    async with app.run_test(size=_SIZE) as pilot:
        app._on_folder_picked(tmp_path)
        await _build(app, pilot)

        assert app.current_plan is not None
        assert app.current_plan.options.destination_root is None
        assert app.current_plan.options.season_folders is False
        [entry] = app.current_plan.entries
        assert entry.destination == tmp_path.resolve() / "Show Name - S01E01 - Pilot.mkv"


@pytest.mark.asyncio
async def test_settings_mode_and_provider_cannot_change_while_a_plan_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.core import apply as core_apply

    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    started, release = threading.Event(), threading.Event()

    def blocking_apply(plan: Plan, *, confirmed: bool) -> list[ApplyResult]:
        started.set()
        release.wait(timeout=10)
        return core_apply.apply_plan(plan, confirmed=confirmed)

    monkeypatch.setattr("termrenamer.tui.app.apply_plan", blocking_apply)
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path, folder_rename=False))
    async with app.run_test(size=_SIZE) as pilot:
        await _show_logs(app, pilot)
        app._on_folder_picked(tmp_path)
        await _build(app, pilot)
        app._apply_current_plan()
        for _ in range(200):
            if started.is_set():
                break
            await pilot.pause(0.05)
        assert started.is_set()
        try:
            for key in ("m", "p", "ctrl+comma"):
                await pilot.press(key)
                await pilot.pause()
            assert app.scan_mode is ScanMode.TV
            assert app.provider_id == "tmdb"
            assert not isinstance(app.screen, SettingsScreen)
            assert _log_text(app).count("cannot change while a Plan is being built") == 3
        finally:
            release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert (tmp_path / "Show Name - S01E01 - Pilot.mkv").is_file()
        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
