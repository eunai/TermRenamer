"""The Queue Stage, driven by keys: the header, the Stages row, the prompt and the queue."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual_fspicker.parts import DirectoryNavigation

from termrenamer.tui.stage import Stage

from .screen_driver import (
    SIZE,
    footer_keys,
    make_app,
    pick_in_dialog,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
    wiring,
)


async def test_the_empty_queue_shows_the_header_the_stages_row_and_the_prompt() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
    assert "TermRenamer" in text
    assert "TV" in text and "Film" in text
    assert "Provider TMDB" in text
    assert "Destination root" in text
    assert "● Queue" in text and "○ Plan" in text and "○ Preview" in text and "○ Applied" in text
    assert "Nothing queued yet" in text
    # The prompt's two buttons, inside its frame (the footer has the same words).
    assert any(
        line.startswith("│") and "a Add file f Add folder" in line for line in text.splitlines()
    )
    assert "Build the Plan" not in text


async def test_the_header_shows_no_key_and_the_destination_root_of_the_mode() -> None:
    app = make_app(wiring(tmdb=False), settings(folder_rename=True, tv_root=Path("/media/Shows")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
    assert "TMDB (no key)" in text
    assert f"Destination root {Path('/media/Shows')}{os.sep}" in text


async def test_the_header_says_the_destination_root_is_not_used_while_folder_rename_is_off(
    tmp_path: Path,
) -> None:
    app = make_app(loaded=settings(tv_root=tmp_path / "Shows"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
    assert "not used: Folder rename is off" in text


async def test_a_opens_the_file_dialog_and_f_the_folder_dialog_and_escape_changes_nothing(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pick_in_dialog(pilot, "a", None)
        await pick_in_dialog(pilot, "f", None)
        assert app.screen is app.screen_stack[0]
        assert app.queue.sources == ()
        assert "Nothing queued yet" in screen_text(app)


@pytest.mark.parametrize("key", ["a", "f"])
async def test_the_dialog_reads_its_listing_styles_only_on_the_app_thread(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The app empties and refills a widget's style table each time it restyles it, so
    # a read of that table from the listing thread can find it empty and stop the app.
    monkeypatch.chdir(tv_backups(tmp_path))
    readers: set[int] = set()
    real_read = DirectoryNavigation.get_component_rich_style

    def spy(self: DirectoryNavigation, *names: str, partial: bool = False) -> object:
        readers.add(threading.get_ident())
        return real_read(self, *names, partial=partial)

    monkeypatch.setattr(DirectoryNavigation, "get_component_rich_style", spy)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, key)
        await app.workers.wait_for_complete()
        await pilot.pause()
        listed = app.screen.query_one(DirectoryNavigation).option_count
        await press(pilot, "escape")
    assert listed > 0
    assert readers == {threading.get_ident()}


@pytest.mark.parametrize("key", ["a", "f"])
async def test_escape_before_the_dialog_has_listed_its_folder_changes_nothing(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A folder on a slow share: its listing holds after the last entry until the test
    # lets it go, so the dialog closes while the listing is still running.
    share = tv_backups(tmp_path).resolve()
    monkeypatch.chdir(share)
    held = threading.Event()
    go = threading.Event()
    real_iterdir = Path.iterdir

    def slow_iterdir(self: Path) -> Iterator[Path]:
        yield from real_iterdir(self)
        if self.resolve() == share:
            held.set()
            go.wait(timeout=10)

    monkeypatch.setattr(Path, "iterdir", slow_iterdir)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, key)
        assert await asyncio.to_thread(held.wait, 10)
        await press(pilot, "escape")
        assert app.screen is app.screen_stack[0]
        go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = screen_text(app)
        lines = [line for _, line in app.log_book.lines_after(0)]
    assert app.queue.sources == ()
    assert "Nothing queued yet" in text
    loud = (" WARNING ", " ERROR ", " CRITICAL ")
    assert not [line for line in lines if any(level in line for level in loud)]


async def test_a_queued_folder_and_file_are_drawn_with_the_queue_actions(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    single = tmp_path / "Night Ferry S01E02.mkv"
    single.write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await pick_in_dialog(pilot, "a", single)
        text = screen_text(app)
        keys = footer_keys(app)
    assert app.queue.sources == (folder.resolve(), single.resolve())
    assert f"TV Backups{os.sep}" in text
    assert "Night Ferry S01E02.mkv" in text
    assert "b Build the Plan" in text and "c Clear the queue" in text
    assert "a Add file" in text and "f Add folder" in text
    assert "Nothing is looked up until you build the Plan." in text
    assert "2 Sources" in text
    assert "b Build Plan" in keys and "c Clear queue" in keys


async def test_the_footer_shows_the_path_of_the_selected_source(tmp_path: Path) -> None:
    first = tv_backups(tmp_path)
    second = tv_backups(tmp_path, "More Backups")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, first, second)
        await press(pilot, "up", "up")
        first_lines = text_of(app, "#stage-lines")
        await press(pilot, "down")
        second_lines = text_of(app, "#stage-lines")
    assert f"path  {first.resolve()}\n" in first_lines
    assert "folder · queued · nothing looked up yet" in first_lines
    assert f"path  {second.resolve()}\n" in second_lines


async def test_a_source_already_queued_is_refused_with_a_message(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder, folder)
        text = screen_text(app)
    assert app.queue.sources == (folder.resolve(),)
    assert "Already queued" in text


async def test_c_clears_the_queue_and_brings_back_the_prompt(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "c")
        text = screen_text(app)
    assert app.queue.sources == ()
    assert "Nothing queued yet" in text
    assert "Queue cleared." in text


async def test_b_with_an_empty_queue_builds_nothing() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stage is Stage.QUEUE
        assert app.plan is None
