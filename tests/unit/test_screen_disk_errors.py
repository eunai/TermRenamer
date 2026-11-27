"""An error from the disk outside a Plan's worker never ends the app.

Each place the screen itself asks the disk (outside a worker that holds its errors) is
driven by its keys with the disk failing there; the app keeps running, the queue and
the settings stay, and the message line says why. The Source pickers have their own
tests in ``test_screen_pickers.py``.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from termrenamer.tui.stage import Stage

from .screen_driver import (
    SIZE,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
)


async def test_a_destination_root_the_disk_fails_to_resolve_at_build_keeps_the_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Library"
    library.mkdir()
    folder = tv_backups(tmp_path).resolve()
    resolve = Path.resolve

    def failing(path: Path, *args: object, **kwargs: object) -> Path:
        if path.name == "Library":
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return resolve(path, *args, **kwargs)  # type: ignore[arg-type]

    app = make_app(loaded=settings(folder_rename=True, tv_root=library))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        monkeypatch.setattr(Path, "resolve", failing)
        await press(pilot, "b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        monkeypatch.setattr(Path, "resolve", resolve)
        message = text_of(app, "#message")
        stage, plan = app.stage, app.plan
        sources, locked = app.queue.sources, app.session_settings.locked
        await press(pilot, "s")
        settings_open = type(app.screen).__name__
        running = app.is_running

    assert running
    assert stage is Stage.QUEUE and plan is None
    assert sources == (folder,)
    assert not locked
    assert settings_open == "SettingsView"
    assert f"The TV Destination root {library} cannot be used: {os.strerror(errno.EIO)}" in (
        message
    )
    assert "No Plan was built." in message


async def test_a_source_the_disk_fails_to_resolve_is_not_queued_and_the_queue_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tv_backups(tmp_path).resolve()
    failing_folder = tmp_path / "Failing"
    failing_folder.mkdir()
    resolve = Path.resolve

    def failing(path: Path, *args: object, **kwargs: object) -> Path:
        if path.name == "Failing":
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return resolve(path, *args, **kwargs)  # type: ignore[arg-type]

    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, first)
        monkeypatch.setattr(Path, "resolve", failing)
        await queue(pilot, failing_folder)
        monkeypatch.setattr(Path, "resolve", resolve)
        message = text_of(app, "#message")
        sources = app.queue.sources
        running = app.is_running

    assert running
    assert sources == (first,)
    assert f"Could not queue {failing_folder}" in message
    assert os.strerror(errno.EIO) in message


async def test_a_queued_source_the_disk_cannot_check_is_still_listed_and_selectable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Queue asks the disk whether each Source is a folder to show it; when the disk
    fails there, the Source is listed as a file and the app keeps running."""
    folder = tv_backups(tmp_path).resolve()
    second = tv_backups(tmp_path, "More Backups").resolve()
    is_dir = Path.is_dir

    def failing(path: Path, *args: object, **kwargs: object) -> bool:
        if path == folder:
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return is_dir(path, *args, **kwargs)  # type: ignore[arg-type]

    app = make_app()
    # Wide enough for the footer's whole path.
    async with app.run_test(size=(240, 36)) as pilot:
        await queue(pilot, folder)
        monkeypatch.setattr(Path, "is_dir", failing)
        # Queuing another Source draws the Queue again, the first Source included.
        await queue(pilot, second)
        await press(pilot, "up")
        text = screen_text(app)
        monkeypatch.setattr(Path, "is_dir", is_dir)
        sources = app.queue.sources
        running = app.is_running

    assert running
    assert sources == (folder, second)
    assert "TV Backups" in text and "More Backups" in text
    assert f"path {folder}" in text
    assert "file · queued · nothing looked up yet" in text


async def test_a_destination_root_with_a_nul_character_from_the_settings_file_builds_nothing(
    tmp_path: Path,
) -> None:
    """A settings file can hold a NUL character in a root, which no path can hold;
    building the Plan says so, shows the NUL as ␀, and keeps the queue."""
    root = Path(f"{tmp_path}{os.sep}bad\x00root")
    folder = tv_backups(tmp_path).resolve()
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=(240, 36)) as pilot:
        await queue(pilot, folder)
        await press(pilot, "b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        message = text_of(app, "#message")
        stage, sources, running = app.stage, app.queue.sources, app.is_running

    assert running and stage is Stage.QUEUE
    assert sources == (folder,)
    assert message == (
        f"The TV Destination root {tmp_path}{os.sep}bad␀root cannot be used: "
        "a path cannot hold a NUL character. No Plan was built."
    )
