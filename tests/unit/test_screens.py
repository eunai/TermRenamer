"""Phase 2 modal/full-screen views: AddSourceQuickPick, HelpScreen, SettingsScreen.

Pilot-driven where practical; otherwise we inspect DEFAULT_CSS / BINDINGS and
dispatch actions directly. No filesystem writes, no live fspicker launches.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.app_bootstrap import Settings
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.screens import AddSourceQuickPick, HelpScreen, SettingsScreen
from termrenamer.tui.screens.footer_bindings import footer_bindings_for_modal
from termrenamer.wiring import PlanningWiring


def _wiring() -> PlanningWiring:
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    return PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        tmdb_api_key="k",
        tvdb_api_key=None,
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=30.0,
        http_max_attempts=4,
        http_backoff_base_seconds=0.5,
        http_jitter=True,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=tmp_path / "films",
        tv_dest_folder=tmp_path / "tv",
    )


# --- footer_bindings_for_modal ------------------------------------------------


def test_footer_bindings_settings_visible_keys() -> None:
    bindings = footer_bindings_for_modal(screen_kind="settings")
    visible = [(b.key, b.description) for b in bindings if b.show]
    assert ("ctrl+comma", "close settings") in visible
    assert ("f1", "open help") in visible


def test_footer_bindings_help_visible_keys() -> None:
    bindings = footer_bindings_for_modal(screen_kind="help")
    visible = [(b.key, b.description) for b in bindings if b.show]
    assert ("f1", "close help") in visible
    assert ("ctrl+comma", "open settings") in visible


def test_footer_bindings_always_include_q_escape_and_noops() -> None:
    for kind in ("settings", "help"):
        bindings = footer_bindings_for_modal(screen_kind=kind)  # type: ignore[arg-type]
        keys = [b.key for b in bindings]
        assert "q" in keys
        assert "escape" in keys
        for shadow in ("m", "p", "b", "a", "ctrl+f"):
            assert shadow in keys, f"{shadow} must be shadowed on {kind} screen"
        assert "ctrl+q" in keys


# --- AddSourceQuickPick -------------------------------------------------------


@pytest.mark.asyncio
async def test_add_source_quick_pick_1_returns_folder() -> None:
    app = TermRenamerApp(wiring=_wiring())
    captured: list[str | None] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddSourceQuickPick(), captured.append)
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert captured == ["folder"]


@pytest.mark.asyncio
async def test_add_source_quick_pick_2_returns_file() -> None:
    app = TermRenamerApp(wiring=_wiring())
    captured: list[str | None] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddSourceQuickPick(), captured.append)
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()

    assert captured == ["file"]


@pytest.mark.asyncio
async def test_add_source_quick_pick_escape_returns_none() -> None:
    app = TermRenamerApp(wiring=_wiring())
    captured: list[str | None] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddSourceQuickPick(), captured.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert captured == [None]


# --- HelpScreen ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_screen_opens_on_f1_and_dismisses_on_q() -> None:
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


def test_help_body_mentions_key_shortcuts() -> None:
    """The help body string contains every Phase 1 keyboard shortcut."""
    from termrenamer.tui.screens.help import HELP_BODY

    text = HELP_BODY.lower()
    for key in ("ctrl+q", "ctrl+f", "ctrl+,", "f1", "[b]m[/b]", "[b]p[/b]", "[b]a[/b]"):
        assert key in text, f"HELP_BODY missing shortcut reference: {key}"


# --- SettingsScreen -----------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_screen_opens_on_ctrl_comma(tmp_path: Path) -> None:
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+comma")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_settings_screen_loads_initial_values_from_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = TermRenamerApp(wiring=_wiring(), settings=settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        tv_input = app.screen.query_one("#tv-destination-input", Input)
        film_input = app.screen.query_one("#film-destination-input", Input)
        assert tv_input.value == str(settings.tv_dest_folder)
        assert film_input.value == str(settings.film_dest_folder)


@pytest.mark.asyncio
async def test_settings_screen_persist_updates_overrides_and_settings_snapshot(
    tmp_path: Path,
) -> None:
    """Saving a TV destination updates ``_settings_overrides`` and replaces ``_settings``."""
    baseline = _settings(tmp_path)
    app = TermRenamerApp(wiring=_wiring(), settings=baseline)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SettingsScreen()
        app.push_screen(screen)
        await pilot.pause()

        override_target = tmp_path / "new_tv"
        tv_input = app.screen.query_one("#tv-destination-input", Input)
        tv_input.value = str(override_target)
        screen.on_input_submitted(Input.Submitted(tv_input, str(override_target)))
        await pilot.pause()

        assert app._settings_overrides.get("tv") == override_target
        assert app._settings is not None
        assert app._settings.tv_dest_folder == override_target


@pytest.mark.asyncio
async def test_settings_button_on_mode_bar_pushes_settings_screen() -> None:
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        btn = app.query_one("#open-settings", Button)
        btn.press()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


# --- Further coverage: action_activate_choice, noop proxies, clear override ---


@pytest.mark.asyncio
async def test_add_source_enter_activates_focused_button() -> None:
    """``Enter`` presses whichever button has focus (``activate_choice``)."""
    app = TermRenamerApp(wiring=_wiring())
    captured: list[str | None] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddSourceQuickPick(), captured.append)
        await pilot.pause()
        btn = app.screen.query_one("#pick-folder", Button)
        btn.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert captured == ["folder"]


@pytest.mark.asyncio
async def test_add_source_button_pick_file_dismisses_with_file() -> None:
    """Clicking the ``pick-file`` button dismisses with ``'file'``."""
    app = TermRenamerApp(wiring=_wiring())
    captured: list[str | None] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddSourceQuickPick(), captured.append)
        await pilot.pause()
        app.screen.query_one("#pick-file", Button).press()
        await pilot.pause()

    assert captured == ["file"]


@pytest.mark.asyncio
async def test_help_screen_proxy_actions_open_settings_and_quit() -> None:
    """Help's proxy actions forward to the main app (``ctrl+comma`` / ``ctrl+q``)."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(HelpScreen())
        await pilot.pause()
        help_screen = app.screen
        assert isinstance(help_screen, HelpScreen)
        help_screen.action_open_settings_proxy()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_settings_screen_empty_save_clears_override(tmp_path: Path) -> None:
    """Submitting an empty string stores ``None`` on the override map."""
    app = TermRenamerApp(wiring=_wiring(), settings=_settings(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SettingsScreen()
        app.push_screen(screen)
        await pilot.pause()
        film_input = app.screen.query_one("#film-destination-input", Input)
        film_input.value = ""
        screen.on_input_submitted(Input.Submitted(film_input, ""))
        await pilot.pause()
        assert app._settings_overrides.get("film") is None
        assert app._settings is not None
        assert app._settings.film_dest_folder is None


@pytest.mark.asyncio
async def test_settings_screen_open_help_proxy_pushes_help() -> None:
    """The ``f1`` proxy from Settings pops back into Help."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.action_open_help_proxy()
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
