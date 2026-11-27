"""Settings, Logs and Help, and the two themes, driven by keys."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from textual.widgets import Input, Switch

from termrenamer.app_bootstrap import ThemeName
from termrenamer.core.models import ScanMode
from termrenamer.tui.keys import KEYS
from termrenamer.tui.stage import Stage
from termrenamer.tui.views import HelpView, LogsView, SettingsView

from .screen_driver import (
    SIZE,
    build,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
)


async def test_s_opens_settings_with_its_five_rows_and_escape_closes_it() -> None:
    app = make_app(loaded=settings(folder_rename=True, tv_root=Path("/media/Shows")))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        assert isinstance(app.screen, SettingsView)
        text = screen_text(app)
        await press(pilot, "escape")
        assert app.screen is app.screen_stack[0]
    for label in (
        "TV Destination root",
        "Film Destination root",
        "Folder rename",
        "Season folder",
        "Theme",
    ):
        assert label in text
    assert str(Path("/media/Shows")) in text
    assert "dark" in text and "light" in text


async def test_a_destination_root_typed_in_settings_is_saved_to_the_settings_owner() -> None:
    app = make_app(loaded=settings(folder_rename=True))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        assert app.focused is app.screen.query_one("#tv-root", Input)
        await pilot.press(*"/media/TV", "enter")
        await press(pilot, "down")
        await pilot.press(*"/media/Films")
        await press(pilot, "escape")
        owner = app.session_settings
        assert owner.destination_root(ScanMode.TV) == Path("/media/TV")
        assert owner.destination_root(ScanMode.FILM) == Path("/media/Films")
        assert f"Destination root {Path('/media/TV')}{os.sep}" in screen_text(app)


async def test_season_folder_cannot_be_turned_on_while_folder_rename_is_off() -> None:
    app = make_app(loaded=settings(folder_rename=True, season_folders=True))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        await press(pilot, "down", "down")
        assert app.focused is app.screen.query_one("#folder-rename", Switch)
        await press(pilot, "enter")
        owner = app.session_settings
        assert not owner.folder_rename and not owner.season_folders
        season = app.screen.query_one("#season-folder", Switch)
        assert season.disabled and not season.value
        text = screen_text(app)
        assert "Season folder works only while Folder rename is on." in text
        await press(pilot, "down")
        await press(pilot, "enter")
        assert not owner.season_folders
        await press(pilot, "up")
        await press(pilot, "enter")
        assert owner.folder_rename
        assert not season.disabled
        await press(pilot, "down", "enter")
        assert owner.season_folders


async def test_the_theme_row_switches_between_dark_and_light_and_discards_nothing(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        assert app.theme == "termrenamer-dark"
        await press(pilot, "s")
        # Season folder is skipped: it is unavailable while Folder rename is off.
        await press(pilot, "down", "down", "down")
        assert app.focused is app.screen.query_one("#theme")
        await press(pilot, "enter")
        assert app.theme == "termrenamer-light"
        assert app.session_settings.theme is ThemeName.LIGHT
        await press(pilot, "space")
        assert app.theme == "termrenamer-dark"
        await press(pilot, "escape")
        assert app.stage is Stage.PREVIEW
        assert app.plan is not None


async def test_the_light_theme_is_used_when_the_settings_ask_for_it() -> None:
    app = make_app(loaded=settings(theme=ThemeName.LIGHT))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.theme == "termrenamer-light"
        assert "gruvbox" not in app.available_themes or app.theme != "gruvbox"


async def test_a_plan_setting_changed_in_settings_discards_the_plan_and_keeps_the_queue(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "s", "down", "down", "enter", "escape")
        assert app.session_settings.folder_rename
        assert app.stage is Stage.QUEUE
        assert app.plan is None
        assert app.queue.sources == (folder.resolve(),)
        assert "Plan discarded: Folder rename changed." in text_of(app, "#message")


async def test_l_opens_the_logs_with_the_session_lines_and_new_ones_as_they_come(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "l")
        assert isinstance(app.screen, LogsView)
        logging.getLogger("termrenamer.test").warning("a line from a library")
        await pilot.pause()
        text = screen_text(app)
        await press(pilot, "escape")
        assert app.screen is app.screen_stack[0]
    assert "Queued" in text and "TV Backups" in text
    assert "WARNING termrenamer.test: a line from a library" in text


async def test_question_mark_opens_help_listing_every_key_of_the_table() -> None:
    app = make_app()
    async with app.run_test(size=(120, 60)) as pilot:
        await press(pilot, "question_mark")
        assert isinstance(app.screen, HelpView)
        text = screen_text(app)
        await press(pilot, "l")
        assert isinstance(app.screen, LogsView)
        await press(pilot, "escape")
        assert app.screen is app.screen_stack[0]
    for key in KEYS:
        assert f"{key.display} {key.where} {key.help_text}" in text


async def test_q_quits_from_a_view() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "question_mark", "q")
        assert not app.is_running


async def test_a_season_folder_loaded_on_while_folder_rename_is_off_is_off() -> None:
    app = make_app(loaded=settings(folder_rename=False, season_folders=True))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s", "down", "down")
        await press(pilot, "enter")  # Folder rename on
        owner = app.session_settings
        season = app.screen.query_one("#season-folder", Switch)
        assert owner.folder_rename
        assert season.value is owner.season_folders is False
        assert owner.plan_options().season_folders is False
        assert text_of(app, "#season-folder-value") == "off"
