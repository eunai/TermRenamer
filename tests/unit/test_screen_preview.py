"""The Preview Stage in full: the selected Title's details, its file cells, the footer's
paths and the summary; and the Apply confirm's text. Driven by keys, read off the screen.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.stages import PreviewStage
from termrenamer.tui.widgets.title_list import TitleList

from .screen_driver import (
    SIZE,
    build,
    lines_with,
    long_season,
    make_app,
    mark_seen_walking,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
    wiring,
)

WIDE = (300, 40)
"""Wide enough that the footer shows each path whole."""


def lines_of(app: object, selector: str) -> list[str]:
    """The lines of one Static, each run of spaces one space."""
    text = text_of(app, selector)  # type: ignore[arg-type]
    return [re.sub(r" {2,}", " ", line).strip() for line in text.splitlines()]


async def test_the_left_column_shows_the_selected_tv_title_and_its_cells(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        first = lines_of(app, "#details-heading")
        cells = text_of(app, "#details-cells")
        await press(pilot, "down", "down")
        not_recognised = lines_of(app, "#details-heading")
    assert first == ["Harbour Lights", "ready · 1 season · 2 videos"]
    assert cells.splitlines()[0].split() == ["██", "██"]
    assert cells.splitlines()[1].split() == ["S01", "██", "██"]
    assert not_recognised == ["holiday.mkv", "not recognised · 1 video"]


async def test_the_left_column_shows_a_film_title_with_its_year(tmp_path: Path) -> None:
    folder = tmp_path / "Film Backups"
    folder.mkdir()
    (folder / "Metropolis (1927).mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        heading = lines_of(app, "#details-heading")
        cells = text_of(app, "#details-cells")
    assert heading == ["Metropolis (1927)", "ready · 1927 · 1 video"]
    assert cells.splitlines()[0].split() == ["██"]


async def test_left_and_right_select_a_file_of_the_title_and_the_footer_follows(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        first = lines_of(app, "#stage-lines")
        await press(pilot, "right")
        second = lines_of(app, "#stage-lines")
        await press(pilot, "right")
        still_second = lines_of(app, "#stage-lines")
        marks = text_of(app, "#details-cells").splitlines()[2]
        await press(pilot, "left")
        back = lines_of(app, "#stage-lines")
        await press(pilot, "down")
        other_title = lines_of(app, "#stage-lines")
    assert first == [
        f"from {folder / 'Harbour Lights S01E01.mkv'}",
        f"to {folder / 'Harbour Lights - S01E01 - The Tide Comes In.mkv'}"
        " · 1 Sidecar moves with it",
    ]
    assert second == [
        f"from {folder / 'Harbour Lights S01E02.mkv'}",
        f"to {folder / 'Harbour Lights - S01E02 - Salt and Rope.mkv'}",
    ]
    assert still_second == second
    assert marks.split() == ["▔▔"] and marks.index("▔") > 6  # under the second cell
    assert back == first
    assert other_title[0] == f"from {folder / 'Night Ferry S01E01.mkv'}"


async def test_in_a_larger_terminal_the_title_list_takes_the_extra_space(tmp_path: Path) -> None:
    widths = {}
    for size in (SIZE, (150, 45)):
        app = make_app()
        async with app.run_test(size=size) as pilot:
            await queue(pilot, tv_backups(tmp_path, f"Backups {size[0]}"))
            await build(pilot)
            preview = app.query_one(PreviewStage)
            widths[size[0]] = (
                preview.query_one("#details").size.width,
                preview.query_one(TitleList).size.width,
            )
            assert "Harbour Lights" in screen_text(app)
    assert widths[150][0] == widths[120][0]
    assert widths[150][1] == widths[120][1] + 30


def mixed_backups(parent: Path) -> Path:
    """Harbour Lights with one video that already has its name, one whose name is taken
    by it and one episode the Provider lacks; a show it does not find; and a video whose
    name cannot be read."""
    folder = parent / "Mixed Backups"
    folder.mkdir()
    for file_name in (
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Harbour Lights - S01E02 - Salt and Rope.mkv",
        "Harbour Lights S01E02.mkv",
        "Harbour Lights S01E09.mkv",
        "Quiet Rivers S01E01.mkv",
        "holiday.mkv",
    ):
        (folder / file_name).write_bytes(b"x")
    return folder


async def test_the_footer_says_for_each_status_where_the_file_goes_or_why_it_stays(
    tmp_path: Path,
) -> None:
    folder = mixed_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        harbour = []
        for _ in range(4):
            harbour.append(lines_of(app, "#stage-lines"))
            await press(pilot, "right")
        await press(pilot, "down")
        quiet = lines_of(app, "#stage-lines")
        await press(pilot, "down")
        holiday = lines_of(app, "#stage-lines")
    assert harbour[0][1] == (
        f"to {folder / 'Harbour Lights - S01E01 - The Tide Comes In.mkv'} · 1 Sidecar moves with it"
    )
    named = folder / "Harbour Lights - S01E02 - Salt and Rope.mkv"
    assert harbour[1] == [f"from {named}", f"to {named} · already has its name"]
    assert harbour[2] == [
        f"from {folder / 'Harbour Lights S01E02.mkv'}",
        f"to {folder / 'Harbour Lights - S01E02 - Salt and Rope (1).mkv'}"
        " · name taken, gets a number",
    ]
    assert harbour[3] == [
        f"from {folder / 'Harbour Lights S01E09.mkv'}",
        "to not renamed · no match: the episode was not found",
    ]
    assert quiet == [
        f"from {folder / 'Quiet Rivers S01E01.mkv'}",
        "to not renamed · no match: the show was not found",
    ]
    assert holiday == [
        f"from {folder / 'holiday.mkv'}",
        "to not renamed · not recognised: its name could not be read",
    ]


async def test_a_sidecar_of_a_video_that_stays_is_counted_as_staying(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    for file_name in ("Quiet Rivers S01E01.mkv", "Quiet Rivers S01E01.srt"):
        (folder / file_name).write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        footer = lines_of(app, "#stage-lines")
    assert footer[1] == "to not renamed · no match: the show was not found · 1 Sidecar stays"


async def test_the_summary_counts_the_videos_of_each_status(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, mixed_backups(tmp_path))
        await build(pilot)
        summary = lines_of(app, "#summary-counts")
        tally = lines_of(app, "#details-tally")
        text = screen_text(app)
    assert summary == [
        "2 ready · 1 name taken",
        "2 no match · 1 not recognised",
        "0 left out",
    ]
    assert tally == ["2 ready · 1 name taken · 1 no match"]
    assert "Nothing moves until you confirm." in text


async def test_a_long_path_keeps_its_file_name_in_the_footer(tmp_path: Path) -> None:
    folder = tmp_path / ("A Very Long Folder Name " * 6).strip()
    folder.mkdir()
    (folder / "Harbour Lights S01E01.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        text = screen_text(app)
    assert lines_with(text, "from …")[0].endswith("Harbour Lights S01E01.mkv")
    assert lines_with(text, "to …")[0].endswith("Harbour Lights - S01E01 - The Tide Comes In.mkv")


async def test_the_apply_confirm_says_what_is_renamed_what_is_skipped_and_why(
    tmp_path: Path,
) -> None:
    folder = mixed_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    assert lines == [
        "Rename 2 videos in their own folders.",
        "Skip 3 videos: 2 no match · 1 not recognised",
        "Leave 1 video that already has its name.",
        "",
        "Nothing has been renamed yet.",
    ]


async def test_the_apply_confirm_names_the_destination_root(tmp_path: Path) -> None:
    root = tmp_path / "TV"
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "enter")
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    assert lines[:2] == [
        f"Rename 3 videos into show folders under {root}{os.sep}.",
        "Skip 1 video: 1 not recognised",
    ]


async def test_the_apply_confirm_says_videos_move_into_show_and_season_folders(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app(loaded=settings(folder_rename=True, season_folders=True))
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        to = lines_of(app, "#stage-lines")[1]
        await press(pilot, "enter")
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    # The Preview moves the video into the show's season folder, in the queued folder.
    moved = (
        folder / "Harbour Lights" / "Season 01" / "Harbour Lights - S01E01 - The Tide Comes In.mkv"
    )
    assert to.startswith(f"to {moved} ·")
    assert (
        lines[0]
        == "Rename 3 videos into show and season folders in the folders they were queued from."
    )


async def test_the_apply_confirm_says_films_move_into_film_folders(tmp_path: Path) -> None:
    folder = tmp_path / "Films"
    folder.mkdir()
    folder = folder.resolve()
    (folder / "Metropolis 1927.mkv").write_bytes(b"x")
    root = tmp_path / "Library"
    app = make_app(loaded=settings(folder_rename=True, film_root=root))
    async with app.run_test(size=WIDE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    assert lines[0] == f"Rename 1 video into a film folder under {root}{os.sep}."


async def test_the_apply_confirm_says_when_nothing_is_skipped(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    (folder / "Night Ferry S01E01.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    assert lines == [
        "Rename 1 video in its own folder.",
        "Skip none.",
        "",
        "Nothing has been renamed yet.",
    ]


async def test_a_rename_that_changes_only_letter_case_is_counted_as_a_rename(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    (folder / "harbour lights - S01E01 - The Tide Comes In.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        footer = lines_of(app, "#stage-lines")
        await press(pilot, "enter")
        lines = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
    assert footer[1] == f"to {folder / 'Harbour Lights - S01E01 - The Tide Comes In.mkv'}"
    assert lines[:2] == ["Rename 1 video in its own folder.", "Skip none."]


async def test_on_a_small_screen_the_selected_file_stays_in_view(tmp_path: Path) -> None:
    folder, tv = long_season(tmp_path, 40)
    app = make_app(wiring(tv=tv), settings())
    async with app.run_test(size=(90, 28)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        overflow = app.query_one("#details-scroll").max_scroll_y
        seen = await mark_seen_walking(pilot, 40)
    assert overflow > 0
    assert seen == "y" * 78
