"""Text the screen did not write itself (a path, a file name, a Provider's name, an error)
reaches the screen as itself: never read as markup, whatever brackets or backslashes it
holds. A Windows folder ends in a backslash, which must not escape what follows it."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path, PureWindowsPath

from termrenamer.core.models import Candidate, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.tui.dialogs.apply_confirm import confirm_lines
from termrenamer.tui.stages.applied import _two_lines
from termrenamer.tui.widgets.footer import AppFooter
from termrenamer.tui.widgets.header import AppHeader

from .screen_driver import (
    SIZE,
    TvStandIn,
    build,
    make_app,
    press,
    queue,
    settings,
    text_of,
    wiring,
)
from .test_plan_stragglers import _options, _two_discs, _write

MARKUP_NAME = "[$accent]x [bold]Harbour Lights[/] $name \\"
"""A Provider's name that reads as markup, a style variable and a value's name included,
ending in a backslash."""

WINDOWS_ROOT = PureWindowsPath("D:\\TV")


def test_an_applied_line_shows_a_windows_folder_and_a_name_in_brackets_as_they_are() -> None:
    source = PureWindowsPath("D:\\Backups\\[Group] Show\\[b]holiday[i].mkv")
    reason = "failed: [Errno 13] Permission denied: 'D:\\TV\\'"

    lines = _two_lines(source, reason, "$error")  # type: ignore[arg-type]

    assert lines.plain.splitlines() == [
        "[b]holiday[i].mkv  D:\\Backups\\[Group] Show\\",
        "    failed: [Errno 13] Permission denied: 'D:\\TV\\'",
    ]


def test_the_apply_confirm_shows_a_windows_root_and_a_provider_name_as_they_are(
    tmp_path: Path,
) -> None:
    show = _two_discs(tmp_path)
    provider = TvStandIn(
        shows={"show name": (Candidate(id="1", name=MARKUP_NAME, year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )
    plan = plan_queue([show], _options(), provider).plan
    plan = dataclasses.replace(
        plan, options=dataclasses.replace(plan.options, destination_root=WINDOWS_ROOT)
    )

    lines = [line.plain for line in confirm_lines(plan)]

    assert lines[0] == "Rename 2 videos under D:\\TV\\."
    assert f"Merge 4 Stragglers ({MARKUP_NAME})" in lines


async def test_the_header_shows_a_windows_root_and_the_provider_as_they_are() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.query_one(AppHeader).show(
            mode=ScanMode.TV,
            provider="[$accent]TMDB[/]",
            has_key=True,
            root=WINDOWS_ROOT,  # type: ignore[arg-type]
            folder_rename=True,
        )
        await pilot.pause()
        root = text_of(app, "#header-root")
        left = text_of(app, "#header-left")

    assert root == "Destination root D:\\TV\\"
    assert "Provider  [$accent]TMDB[/] ▾ " in left


async def test_a_message_shows_a_windows_folder_and_brackets_as_they_are() -> None:
    message = "Cannot read D:\\Backups\\[$accent]x[/]\\: [Errno 13] Permission denied $text"
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.query_one(AppFooter).show_message(message)
        await pilot.pause()
        shown = text_of(app, "#message")

    assert shown == message


async def test_names_in_brackets_reach_every_stage_as_they_are(tmp_path: Path) -> None:
    folder = tmp_path / "[Group] TV[i]"
    _write(folder / "Harbour Lights S01E01.mkv")
    _write(folder / "[b]holiday[i].mkv")
    folder = folder.resolve()
    provider = TvStandIn(
        shows={"harbour lights": (Candidate(id="11", name=MARKUP_NAME, year=2019),)},
        episodes={("11", 1, 1): "The Tide Comes In"},
    )
    app = make_app(wired=wiring(tv=provider), loaded=settings())
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        queued = text_of(app, "#stage-lines").splitlines()[0]
        await build(pilot)
        heading = text_of(app, "#details-heading").splitlines()[0]
        source = text_of(app, "#stage-lines").splitlines()[0]
        await press(pilot, "down")
        other_heading = text_of(app, "#details-heading").splitlines()[0]
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await press(pilot)
        listed = text_of(app, "#applied-list").splitlines()

    assert queued == f"path  {folder}"
    assert source.endswith(f"[Group] TV[i]{os.sep}Harbour Lights S01E01.mkv")
    assert {heading, other_heading} == {MARKUP_NAME, "[b]holiday[i].mkv"}
    assert listed[:2] == [
        f"[b]holiday[i].mkv  {folder}{os.sep}",
        "    not recognised: its name could not be read",
    ]
