"""Text the screen did not write itself (a path, a file name, a Provider's name, an error)
reaches the screen as itself: never read as markup, whatever brackets or backslashes it
holds. A Windows folder ends in a backslash, which must not escape what follows it.

Each test drives the app to the Stage or dialog that shows the text and reads the screen.
The folders are real, in the test's temporary folder, so on Windows each folder the
screen writes ends in a backslash of its own."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from textual.pilot import Pilot

from termrenamer.core.models import Candidate

from .screen_driver import (
    POSTERS_AVAILABLE,
    SIZE,
    FilmStandIn,
    ImageHost,
    TvStandIn,
    build,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    wiring,
)
from .test_plan_stragglers import _two_discs, _write
from .test_screen_pick_match import picker_lines

MARKUP_NAME = "[$accent]x [bold]Harbour Lights[/] $name \\"
"""A Provider's name that reads as markup, a style variable and a value's name included,
ending in a backslash."""

FOLDER_NAMES = [
    pytest.param("[$accent]x [b]TV[i] $text", id="markup"),
    pytest.param("[Group] TV", id="group"),
    pytest.param(
        "[Group] TV \\",
        id="backslash",
        marks=pytest.mark.skipif(
            sys.platform == "win32",
            reason="a Windows file name cannot hold a backslash: it separates folders",
        ),
    ),
]
"""Folder names that read as markup; the last ends in a backslash."""


async def _apply(pilot: Pilot[None]) -> None:
    await press(pilot, "enter", "y")
    await pilot.app.workers.wait_for_complete()
    await press(pilot)


@pytest.mark.parametrize("name", FOLDER_NAMES)
async def test_an_applied_line_shows_a_folder_a_name_and_a_reason_in_brackets_as_they_are(
    tmp_path: Path, name: str
) -> None:
    folder = tmp_path / name
    _write(folder / "[b]holiday[i].mkv")
    _write(folder / "Night Ferry S01E01.mkv")
    folder = folder.resolve()
    root = tmp_path / "[$accent]x Root"
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        root.write_bytes(b"a file where the Destination root's folder should be")
        await _apply(pilot)
        listed = text_of(app, "#applied-list").splitlines()

    assert listed[:3] == [
        f"[b]holiday[i].mkv  {folder}{os.sep}",
        "    not recognised: its name could not be read",
        f"Night Ferry S01E01.mkv  {folder}{os.sep}",
    ]
    assert listed[3].startswith("    failed: mkdir failed: [")  # [Errno …] or [WinError …]
    assert root.name in listed[3]


@pytest.mark.parametrize("name", FOLDER_NAMES)
async def test_the_apply_confirm_shows_a_destination_root_and_a_provider_name_as_they_are(
    tmp_path: Path, name: str
) -> None:
    show = _two_discs(tmp_path)
    root = tmp_path / name
    root.mkdir()
    provider = TvStandIn(
        shows={"show name": (Candidate(id="1", name=MARKUP_NAME, year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )
    loaded = settings(folder_rename=True, season_folders=True, tv_root=root)
    app = make_app(wiring(tv=provider), loaded)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, show)
        await build(pilot)
        await press(pilot, "enter")
        lines = text_of(app, "#confirm-lines").splitlines()
        await press(pilot, "n")

    assert lines[0] == f"Rename 2 videos into show and season folders under {root}{os.sep}."
    assert f"Merge 4 Stragglers ({MARKUP_NAME})" in lines


@pytest.mark.parametrize("name", FOLDER_NAMES)
async def test_the_header_shows_a_destination_root_as_it_is(tmp_path: Path, name: str) -> None:
    root = tmp_path / name
    root.mkdir()
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()  # the app draws the header again on its first resize
        shown = text_of(app, "#header-root")
        left = text_of(app, "#header-left")

    assert shown == f"Destination root {root}{os.sep}"
    assert "Provider  TMDB ▾ " in left


@pytest.mark.parametrize("name", FOLDER_NAMES)
async def test_a_message_shows_a_folder_in_brackets_as_it_is(tmp_path: Path, name: str) -> None:
    folder = tmp_path / name
    folder.mkdir()
    folder = folder.resolve()
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        queued = text_of(app, "#message")
        await queue(pilot, folder)
        refused = text_of(app, "#message")

    assert queued == f"Queued {folder}."
    assert refused == f"Already queued: {folder}"


async def test_a_message_shows_a_provider_name_in_brackets_as_it_is(tmp_path: Path) -> None:
    first = Candidate(id="1", name="Heat", year=1995)
    second = Candidate(id="2", name=MARKUP_NAME, year=1986)
    films = FilmStandIn(films={("heat", 1995): (first, second)})
    folder = tmp_path / "Films"
    _write(folder / "Heat.1995.mkv")
    app = make_app(wired=wiring(film=films))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "t")
        await press(pilot, "2")
        await app.workers.wait_for_complete()
        await pilot.pause()
        message = text_of(app, "#message")

    assert message == f"Heat (1995) now matches {MARKUP_NAME} (1986)."


@pytest.mark.parametrize("name", FOLDER_NAMES)
async def test_names_in_brackets_reach_every_stage_as_they_are(tmp_path: Path, name: str) -> None:
    folder = tmp_path / name
    _write(folder / "Harbour Lights S01E01.mkv")
    _write(folder / "Night Ferry S01E01.mkv")
    _write(folder / "[b]holiday[i].mkv")
    folder = folder.resolve()
    # The second search waits until the test lets it go, so the Plan Stage is read mid-build.
    provider = TvStandIn(
        shows={
            "harbour lights": (Candidate(id="11", name=MARKUP_NAME, year=2019),),
            "night ferry": (Candidate(id="12", name="Night Ferry", year=2021),),
        },
        episodes={("11", 1, 1): "The Tide Comes In", ("12", 1, 1): "Cast Off"},
        hold=True,
    )
    app = make_app(wired=wiring(tv=provider), loaded=settings())
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        queued = text_of(app, "#stage-lines").splitlines()[0]
        queue_screen = screen_text(app)
        await press(pilot, "b")
        assert provider.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        building = screen_text(app)
        plan_heading = text_of(app, "#plan-details").splitlines()[0]
        provider.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        heading = text_of(app, "#details-heading").splitlines()[0]
        source = text_of(app, "#stage-lines").splitlines()[0]
        await press(pilot, "down", "down")
        other_heading = text_of(app, "#details-heading").splitlines()[0]
        await _apply(pilot)
        listed = text_of(app, "#applied-list").splitlines()

    assert queued == f"path  {folder}"
    assert f"└── {folder.name}{os.sep} " in queue_screen
    assert "Building the Plan…" in building
    assert plan_heading == MARKUP_NAME
    assert f"{MARKUP_NAME} found 1" in building
    assert "Night Ferry looking up 1" in building
    assert "[b]holiday[i].mkv not recognised 1" in building
    assert source.endswith(f"{folder.name}{os.sep}Harbour Lights S01E01.mkv")
    assert {heading, other_heading} == {MARKUP_NAME, "[b]holiday[i].mkv"}
    assert listed[:2] == [
        f"[b]holiday[i].mkv  {folder}{os.sep}",
        "    not recognised: its name could not be read",
    ]


async def test_the_match_picker_shows_candidates_names_as_they_are(tmp_path: Path) -> None:
    first = Candidate(id="1", name="[$accent]Heat[/] \\", year=1995)
    second = Candidate(id="2", name="[Group] Heat[i]", year=1986)
    films = FilmStandIn(films={("heat", 1995): (first, second)})
    folder = tmp_path / "Films"
    _write(folder / "Heat.1995.mkv")
    app = make_app(wired=wiring(film=films))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "t")
        lines = picker_lines(app)
        now = text_of(app, "#picker-now")
        text = screen_text(app)

    assert now == "Now: [$accent]Heat[/] \\ (1995)"
    assert lines == [
        "▸ 1 [$accent]Heat[/] \\ (1995) (current)",
        "2 [Group] Heat[i] (1986)",
        "/ Type a title",
    ]
    assert "Pick a match for [$accent]Heat[/] \\ (1995) · TMDB" in text


async def test_the_match_picker_tiles_show_candidates_names_as_they_are(tmp_path: Path) -> None:
    first = Candidate(id="1", name="[$accent]Heat \\", year=1995, poster_ref="/heat.jpg")
    second = Candidate(id="2", name="[Group] Heat[i]", year=1986)
    films = FilmStandIn(films={("heat", 1995): (first, second)})
    folder = tmp_path / "Films"
    _write(folder / "Heat.1995.mkv")
    host = ImageHost(status=404)
    wired = wiring(film=films, posters=host.store(tmp_path / "posters"))
    app = make_app(wired=wired, posters=POSTERS_AVAILABLE)
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "t")
        await app.workers.wait_for_complete()
        await app.screen.workers.wait_for_complete()
        await pilot.pause()
        names = [text_of(app, f"#picker-tile-{n} .tile-name") for n in (0, 1)]
        text = screen_text(app)

    assert names == ["[$accent]Heat \\", "[Group] Heat[i]"]
    # In place of each Poster: the name, then "no poster".
    assert "┃ [$accent]Heat \\ ┃" in text
    assert "│ [Group] Heat[i] │" in text
