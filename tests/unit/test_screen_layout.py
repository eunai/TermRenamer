"""Controls stay on screen however long a list or a confirm is, at the four checked sizes.

Driven by keys, read off the screen: a control counts as on screen when the screen
draws it, at its top-left cell, inside the terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from textual.widget import Widget

from termrenamer.core.policies import NameTakenPolicy
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.dialogs import ApplyConfirm, UndoConfirm
from termrenamer.tui.stage import Stage

from .screen_driver import (
    TvStandIn,
    build,
    long_season,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    wiring,
)

SIZES = [(90, 28), (100, 30), (100, 35), (120, 36)]


def drawn(app: TermRenamerApp, selector: str) -> bool:
    """Whether the widget ``selector`` of the top screen is drawn, inside the terminal,
    at its top-left cell: nothing covers it and no scroll hides it."""
    widget = app.screen.query_one(selector, Widget)
    region = widget.region
    width, height = app.size
    if not region.area or region.right > width or region.bottom > height:
        return False
    try:
        found, _ = app.screen.get_widget_at(region.x, region.y)
    except Exception:  # noqa: BLE001 - nothing drawn there
        return False
    return found is widget or widget in found.ancestors


def season_with_taken_sidecars(parent: Path, videos: int) -> tuple[Path, TvStandIn]:
    """``videos`` episodes of Harbour Lights, each with a subtitle whose new name is
    taken already, so under Name taken ``skip`` each Sidecar is skipped alone; and the
    TV stand-in that knows each episode."""
    folder, tv = long_season(parent, videos)
    for episode in range(1, videos + 1):
        (folder / f"Harbour Lights S01E{episode:02d}.srt").write_bytes(b"s")
        (folder / f"Harbour Lights - S01E{episode:02d} - Episode {episode}.srt").write_bytes(b"t")
    return folder.resolve(), tv


@pytest.mark.parametrize("size", SIZES)
async def test_the_apply_confirm_keeps_both_buttons_on_screen_with_a_long_list(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    folder, tv = season_with_taken_sidecars(tmp_path, 32)
    app = make_app(wiring(tv=tv), settings(name_taken=NameTakenPolicy.SKIP))
    async with app.run_test(size=size) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        yes, no = drawn(app, "#confirm-yes"), drawn(app, "#confirm-no")
        first = screen_text(app)
        await press(pilot, "end")
        last = screen_text(app)
        await press(pilot, "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        stage = app.stage

    assert yes and no
    assert "Rename 32 videos" in first
    assert "Nothing has been renamed yet." in last
    assert stage is Stage.APPLIED


@pytest.mark.parametrize("size", SIZES)
async def test_the_undo_confirm_keeps_both_buttons_on_screen(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    folder, tv = long_season(tmp_path, 3)
    app = make_app(wiring(tv=tv))
    async with app.run_test(size=size) as pilot:
        await queue(pilot, folder.resolve())
        await build(pilot)
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await press(pilot, "u")
        assert isinstance(app.screen, UndoConfirm)
        yes, no = drawn(app, "#confirm-yes"), drawn(app, "#confirm-no")

    assert yes and no


@pytest.mark.parametrize("size", SIZES)
async def test_a_long_queue_scrolls_above_its_four_buttons(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    folders = []
    for n in range(40):
        folder = tmp_path / f"Backups {n:02d}"
        folder.mkdir()
        folders.append(folder.resolve())
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await queue(pilot, *folders)
        names = ("queue-build", "queue-clear", "queue-add-file", "queue-add-folder")
        buttons = {name: drawn(app, f"#{name}") for name in names}
        top = screen_text(app)
        # The tree scrolls to the selected Source; the buttons stay.
        await press(pilot, *["down"] * 39)
        bottom = screen_text(app)
        still = {name: drawn(app, f"#{name}") for name in names}

    assert buttons == dict.fromkeys(names, True)
    assert still == dict.fromkeys(names, True)
    assert f"Backups 00{os.sep}" in top
    assert f"Backups 39{os.sep}" not in top
    assert f"Backups 39{os.sep}" in bottom
