"""The Source pickers and every typed path: a path shows as written, and a folder that
cannot be read or a path that cannot be expanded never ends the app.

Driven by keys on the screen, with the folders in each test's temporary folder.
"""

from __future__ import annotations

import errno
import os
import sys
import threading
from pathlib import Path

import pytest
from textual import events
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
    tv_backups,
    until,
)

WIDE = (200, 36)
"""Wide enough that the picker shows its whole folder."""


async def wait_for_listing(pilot: object) -> None:
    app = pilot.app  # type: ignore[attr-defined]
    await app.workers.wait_for_complete()
    await pilot.pause()  # type: ignore[attr-defined]


@pytest.mark.parametrize("key", ["a", "f"])
async def test_a_long_folder_of_wide_characters_keeps_its_last_name_on_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """Each of these characters takes two cells: the folder is cut from the left by
    cells, so its end, the folder's own name, is what shows."""
    start = tmp_path / ("映画のフォルダ" * 8) / "番組"
    start.mkdir(parents=True)
    monkeypatch.chdir(start)
    app = make_app()
    async with app.run_test(size=(90, 28)) as pilot:
        await press(pilot, key)
        await wait_for_listing(pilot)
        lines = [line for line in screen_text(app).splitlines() if "…" in line]
        await press(pilot, "escape")

    assert any(f"{os.sep}番組" in line for line in lines), lines


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
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))
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
    assert f"This folder cannot be read: {os.strerror(errno.ENOENT)}" in text
    assert running and main
    assert sources == (queued.resolve(),)


@pytest.mark.parametrize("key", ["a", "f"])
async def test_a_folder_refused_with_its_parent_keeps_the_app_and_the_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """Neither the folder nor its ``..`` can be read, as when browsing into a folder of
    another user: the dialog stays open, empty, and says why."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Refused").resolve()
    start.mkdir()
    monkeypatch.chdir(start)
    listed, stat = Path.iterdir, Path.stat
    parent = start / ".."

    def refused(path: Path):  # type: ignore[no-untyped-def]
        if path == start:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return listed(path)

    def refused_stat(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == parent:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return stat(path, *args, **kwargs)  # type: ignore[arg-type]

    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        monkeypatch.setattr(Path, "iterdir", refused)
        monkeypatch.setattr(Path, "stat", refused_stat)
        await press(pilot, key)
        await wait_for_listing(pilot)
        dialog = app.screen
        text = screen_text(app)
        monkeypatch.setattr(Path, "iterdir", listed)
        monkeypatch.setattr(Path, "stat", stat)
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running

    assert isinstance(dialog, FileOpen if key == "a" else SelectDirectory)
    assert f"This folder cannot be read: {os.strerror(errno.EACCES)}" in text
    assert running
    assert sources == (queued.resolve(),)


@pytest.mark.parametrize("number", [errno.EACCES, errno.ENAMETOOLONG])
async def test_a_typed_path_the_disk_cannot_answer_gets_no_suggestion_and_keeps_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int
) -> None:
    """The file dialog suggests as the person types; a path the disk refuses to look at
    gets no suggestion, so ``→`` at the end of the text adds nothing to it, and the
    dialog, the typed text and the queue stay."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Start").resolve()
    (start / "Locked").mkdir(parents=True)
    monkeypatch.chdir(start)
    exists = Path.exists

    def refused(path: Path, *args: object, **kwargs: object) -> bool:
        if "Locked" in path.parts:
            raise OSError(number, os.strerror(number), str(path))
        return exists(path, *args, **kwargs)  # type: ignore[arg-type]

    typed = f"Locked{os.sep}x"
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        await press(pilot, "a")
        await wait_for_listing(pilot)
        monkeypatch.setattr(Path, "exists", refused)
        field = app.screen.query_one(Input)
        await pilot.press("tab")
        assert app.focused is field
        await pilot.press(*typed)
        await wait_for_listing(pilot)
        await pilot.pause()
        # → at the end of the text takes the suggestion shown, if there is one.
        await pilot.press("right")
        shown = field.value
        dialog = app.screen
        monkeypatch.setattr(Path, "exists", exists)
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running

    assert isinstance(dialog, FileOpen)
    assert shown == typed
    assert running
    assert sources == (queued.resolve(),)


@pytest.mark.parametrize(
    ("number", "said"),
    [
        (errno.ENAMETOOLONG, "This path cannot be used: {}"),
        # The folder that holds it cannot be looked in.
        (errno.EACCES, "This folder cannot be read: {}"),
    ],
)
async def test_enter_on_a_typed_path_the_disk_cannot_answer_says_why_and_keeps_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int, said: str
) -> None:
    """Enter on a typed path leaves the file dialog open with the reason on its error
    line when the disk cannot say what the path is; the typed text and the queue stay."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Start").resolve()
    start.mkdir()
    monkeypatch.chdir(start)
    is_dir = Path.is_dir

    def refused(path: Path, *args: object, **kwargs: object) -> bool:
        if path.name == "Too long":
            raise OSError(number, os.strerror(number), str(path))
        return is_dir(path, *args, **kwargs)  # type: ignore[arg-type]

    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        await press(pilot, "a")
        await wait_for_listing(pilot)
        field = app.screen.query_one(Input)
        await pilot.press("tab")
        assert app.focused is field
        await pilot.press(*"Too long")
        monkeypatch.setattr(Path, "is_dir", refused)
        await pilot.press("enter")
        await wait_for_listing(pilot)
        text = screen_text(app)
        dialog = app.screen
        shown = field.value
        monkeypatch.setattr(Path, "is_dir", is_dir)
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running

    assert isinstance(dialog, FileOpen)
    # The system's own words for the error: Windows words ENAMETOOLONG its own way.
    assert said.format(os.strerror(number)) in text
    assert shown == "Too long"
    assert running
    assert sources == (queued.resolve(),)


@pytest.mark.skipif(
    sys.platform == "win32", reason="a Windows folder has no search permission to take away"
)
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="the superuser reads any folder"
)
async def test_a_folder_that_lists_but_cannot_be_entered_says_why_in_the_folder_picker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its names can be read, but not one of them can be looked at, ``..`` included (read
    but no search permission): the listing is empty and says why."""
    start = (tmp_path / "Start").resolve()
    unsearchable = start / "Unsearchable"
    (unsearchable / "Inside").mkdir(parents=True)
    monkeypatch.chdir(start)
    app = make_app()
    try:
        async with app.run_test(size=WIDE) as pilot:
            await press(pilot, "f")
            await wait_for_listing(pilot)
            unsearchable.chmod(0o444)
            # The listing holds ``..`` then Unsearchable.
            await pilot.press("down", "enter")
            await wait_for_listing(pilot)
            await pilot.pause()
            text = screen_text(app)
            dialog = app.screen
            await press(pilot, "escape")
            running = app.is_running
    finally:
        unsearchable.chmod(0o755)

    assert isinstance(dialog, SelectDirectory)
    assert f"This folder cannot be read: {os.strerror(errno.EACCES)}" in text
    assert running


@pytest.mark.parametrize(("key", "kind"), [("a", FileOpen), ("f", SelectDirectory)])
@pytest.mark.parametrize("call", ["is_dir", "resolve"])
async def test_choosing_a_listed_folder_the_disk_cannot_answer_for_says_why_and_keeps_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, kind: type, call: str
) -> None:
    """Enter on a listed folder checks it on the disk; when the disk fails there, the
    dialog stays open on its folder and says why, and the queue stays."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Start").resolve()
    inside = start / "Inside"
    inside.mkdir(parents=True)
    monkeypatch.chdir(start)
    real = getattr(Path, call)

    def failing(path: Path, *args: object, **kwargs: object) -> object:
        if path.name == "Inside":
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return real(path, *args, **kwargs)

    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        await press(pilot, key)
        await wait_for_listing(pilot)
        monkeypatch.setattr(Path, call, failing)
        # The listing holds ``..`` then Inside.
        await pilot.press("down", "enter")
        await wait_for_listing(pilot)
        text = screen_text(app)
        dialog = app.screen
        monkeypatch.setattr(Path, call, real)
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running

    assert isinstance(dialog, kind)
    assert f"This path cannot be used: {os.strerror(errno.EIO)}" in text
    # Still on its own folder (the folder dialog cuts a long one from the left).
    assert f"{os.sep}Start " in text
    assert running
    assert sources == (queued.resolve(),)


@pytest.mark.parametrize("key", ["a", "f"])
async def test_a_folder_left_before_its_listing_ends_changes_nothing_shown_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """The person goes up from a folder still being listed; when that listing then
    fails, the folder above keeps its entries and no error line is shown for it."""
    parent = (tmp_path / "Parent").resolve()
    child = parent / "Child"
    child.mkdir(parents=True)
    (parent / "Sibling").mkdir()
    monkeypatch.chdir(child)
    listed = Path.iterdir
    held, release = threading.Event(), threading.Event()

    def slow(path: Path) -> object:
        if path == child:
            held.set()
            assert release.wait(timeout=10)
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return listed(path)

    monkeypatch.setattr(Path, "iterdir", slow)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await press(pilot, key)
        assert held.wait(timeout=5)
        await press(pilot, "backspace")
        await until(pilot, lambda: "Sibling" in screen_text(app))
        release.set()
        await wait_for_listing(pilot)
        await pilot.pause()
        text = screen_text(app)
        await press(pilot, "escape")
        running = app.is_running

    assert "Sibling" in text
    assert "cannot be read" not in text
    assert running


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


async def test_a_root_pasted_with_a_nul_character_is_refused_and_build_keeps_the_app(
    tmp_path: Path,
) -> None:
    """No path can hold a NUL character: Settings refuses one pasted into a root and
    keeps the root set before, so building the Plan afterwards works."""
    root = tmp_path / "TV"
    root.mkdir()
    queued = tv_backups(tmp_path).resolve()
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, queued)
        await press(pilot, "s")
        field = app.screen.query_one("#tv-root", Input)
        await pilot.press("end", "ctrl+u")
        field.post_message(events.Paste(f"{tmp_path}{os.sep}bad\x00root"))
        await pilot.pause()
        await press(pilot, "enter")
        message = text_of(app, "#settings-message")
        await press(pilot, "escape")
        kept = app.session_settings.destination_root(ScanMode.TV)
        await press(pilot, "b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        running, plan = app.is_running, app.plan

    assert message.startswith(
        f"The TV Destination root {tmp_path}{os.sep}bad␀root cannot be used "
        "(a path cannot hold a NUL character); it is still "
    )
    assert kept == root
    assert running and plan is not None


async def test_enter_on_a_typed_name_with_a_nul_character_says_why_and_keeps_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A NUL character, pasted as a terminal allows, is in no path: Enter says so and the
    dialog and the queue stay."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Start").resolve()
    start.mkdir()
    monkeypatch.chdir(start)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        await press(pilot, "a")
        await wait_for_listing(pilot)
        field = app.screen.query_one(Input)
        await pilot.press("tab")
        assert app.focused is field
        field.post_message(events.Paste("bad\x00name"))
        await pilot.pause()
        await press(pilot, "enter")
        text = screen_text(app)
        dialog = app.screen
        await press(pilot, "escape")
        sources = app.queue.sources
        running = app.is_running

    assert isinstance(dialog, FileOpen)
    assert "This path cannot be used: a path cannot hold a NUL character" in text
    assert running
    assert sources == (queued.resolve(),)


@pytest.mark.parametrize("pasted", ["a\x00b/c", "~\x00/x"])
async def test_a_typed_path_with_a_nul_character_gets_no_suggestion_and_keeps_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pasted: str
) -> None:
    """The suggester looks in the folder the typed text names; one holding a NUL
    character names none, so there is no suggestion, and the dialog and queue stay."""
    queued = tmp_path / "Queued"
    queued.mkdir()
    start = (tmp_path / "Start").resolve()
    start.mkdir()
    monkeypatch.chdir(start)
    typed = pasted.replace("/", os.sep)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, queued.resolve())
        await press(pilot, "a")
        await wait_for_listing(pilot)
        field = app.screen.query_one(Input)
        await pilot.press("tab")
        assert app.focused is field
        field.post_message(events.Paste(typed))
        await pilot.pause()
        await app.screen.workers.wait_for_complete()
        await pilot.press("right")
        await pilot.pause()
        value, dialog = field.value, app.screen
        await press(pilot, "escape")
        sources, running = app.queue.sources, app.is_running

    assert running
    assert isinstance(dialog, FileOpen)
    assert value == typed
    assert sources == (queued.resolve(),)
