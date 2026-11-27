"""The Source pickers and every typed path: a path shows as written, and a folder that
cannot be read or a path that cannot be expanded never ends the app.

Driven by keys on the screen, with the folders in each test's temporary folder.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

import pytest
from textual.widgets import Input
from textual_fspicker import FileOpen, SelectDirectory

from termrenamer.core.models import ScanMode
from termrenamer.tui.views import SettingsView

from .screen_driver import (
    SIZE,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
)

WIDE = (200, 36)
"""Wide enough that the picker shows its whole folder."""

NAMES = ["[$accent]x", "[Group] Show", "[b]holiday[i]"]
"""Folder names that read as markup."""
if sys.platform != "win32":
    NAMES.append("ends in a backslash \\")


async def wait_for_listing(pilot: object) -> None:
    app = pilot.app  # type: ignore[attr-defined]
    await app.workers.wait_for_complete()
    await pilot.pause()  # type: ignore[attr-defined]


@pytest.mark.parametrize("key", ["a", "f"])
@pytest.mark.parametrize("name", NAMES)
async def test_both_pickers_show_their_folder_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, name: str
) -> None:
    start = tmp_path / name
    start.mkdir()
    monkeypatch.chdir(start)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await press(pilot, key)
        await wait_for_listing(pilot)
        assert isinstance(app.screen, FileOpen if key == "a" else SelectDirectory)
        text = screen_text(app)
        await press(pilot, "escape")
    # The picker cuts a long folder from the left; its last two names are shown.
    assert f"{start.parent.name}{os.sep}{name}" in text


@pytest.mark.parametrize("key", ["a", "f"])
async def test_a_folder_gone_before_the_picker_lists_it_keeps_the_app_and_the_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Vanishing").resolve()
    start.mkdir()
    monkeypatch.chdir(start)
    listed = Path.iterdir

    def vanished(path: Path):  # type: ignore[no-untyped-def]
        if path == start:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
        return listed(path)

    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        # The folder goes between the dialog opening and its listing.
        monkeypatch.setattr(Path, "iterdir", vanished)
        await press(pilot, key)
        await wait_for_listing(pilot)
        dialog = app.screen
        text = screen_text(app)
        monkeypatch.setattr(Path, "iterdir", listed)
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running
        main = app.screen is app.screen_stack[0]

    assert isinstance(dialog, FileOpen if key == "a" else SelectDirectory)
    assert "This folder cannot be read: No such file or directory" in text
    assert running and main
    assert sources == (queued.resolve(),)


async def test_a_root_with_an_unknown_user_in_settings_is_refused_and_the_old_one_kept(
    tmp_path: Path,
) -> None:
    root = tmp_path / "TV"
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        assert app.focused is app.screen.query_one("#tv-root", Input)
        await pilot.press("end", "ctrl+u", *"~nonexistent-user-of-termrenamer/TV", "enter")
        await pilot.pause()
        message = text_of(app, "#settings-message")
        still = isinstance(app.screen, SettingsView)
        await press(pilot, "escape")
        kept = app.session_settings.destination_root(ScanMode.TV)
        running = app.is_running

    assert still and running
    assert message.startswith("The TV Destination root ~nonexistent-user-of-termrenamer")
    assert "cannot be used" in message
    assert kept == root
