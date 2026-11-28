"""The mouse on the screen's lists: a click on a row selects it exactly as the arrows do.

The highlight, the details, the footer's paths, the Poster and the file that ``x`` and
``t`` act on always agree. Driven by clicks and keys, read off the screen.
"""

from __future__ import annotations

from pathlib import Path

from textual.pilot import Pilot

from termrenamer.tui.stage import Stage
from termrenamer.tui.widgets.title_list import TitleList

from .screen_driver import (
    POSTERS_AVAILABLE,
    ImageHost,
    build,
    lines_with,
    make_app,
    press,
    queue,
    screen_text,
    text_of,
    tv_backups,
    tv_stand_in,
    wiring,
)

WIDE = (300, 40)
"""Wide enough that the footer shows each path whole."""


async def click_row(pilot: Pilot[None], list_id: str, name: str) -> None:
    """Click the row of the Title list ``list_id`` whose name starts with ``name``."""
    titles = pilot.app.query_one(f"#{list_id}", TitleList)
    index = next(i for i, row in enumerate(titles.rows) if row.name.startswith(name))
    await pilot.click(f"#{list_id}", offset=(4, index - int(titles.scroll_y)))
    await pilot.pause()


def footer_from(app: object) -> str:
    return text_of(app, "#stage-lines").splitlines()[0].split(maxsplit=1)[1]  # type: ignore[arg-type]


async def test_a_click_on_a_preview_row_selects_it_as_the_arrows_do(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "right")  # Harbour Lights, its second episode
        await click_row(pilot, "preview-titles", "Night Ferry")
        heading = text_of(app, "#details-heading").splitlines()[0]
        source = footer_from(app)
        await press(pilot, "x")
        text = screen_text(app)
        heading_after = text_of(app, "#details-heading").splitlines()[0]

    assert heading == "Night Ferry"
    assert source == str(folder / "Night Ferry S01E01.mkv")
    # x left out the video shown, and only it.
    assert heading_after == "Night Ferry"
    assert any(line.endswith("left out 1") for line in lines_with(text, "Night Ferry"))
    assert any(line.endswith("ready 2") for line in lines_with(text, "Harbour Lights"))


async def test_a_click_then_t_opens_the_picker_for_the_clicked_title(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await click_row(pilot, "preview-titles", "Night Ferry")
        await press(pilot, "t")
        heading = str(app.screen.query_one("#picker-dialog").border_title)

    assert "Pick a match for Night Ferry" in heading


async def test_a_click_starts_at_the_first_file_of_the_title(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await click_row(pilot, "preview-titles", "Night Ferry")
        await click_row(pilot, "preview-titles", "Harbour Lights")
        source = footer_from(app)
        marks = text_of(app, "#details-cells").splitlines()[2]

    assert source == str(folder / "Harbour Lights S01E01.mkv")
    assert marks.lstrip().startswith("▔▔") and marks.split() == ["▔▔"]


async def test_a_click_on_a_preview_row_shows_that_titles_poster(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    host = ImageHost()
    app = make_app(wiring(posters=host.store(tmp_path / "posters")), posters=POSTERS_AVAILABLE)
    async with app.run_test(size=(120, 36)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await app.workers.wait_for_complete()
        await pilot.pause()
        first = screen_text(app)
        await click_row(pilot, "preview-titles", "Night Ferry")
        await app.workers.wait_for_complete()
        await pilot.pause()
        after = screen_text(app)

    assert "POSTER" in first
    # Night Ferry has no Poster reference: the panel names it and shows none.
    assert "POSTER" not in after
    assert "Night Ferry" in after


async def test_a_click_on_a_plan_row_shows_that_titles_details(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    tv = tv_stand_in(hold=True)
    app = make_app(wiring(tv=tv))
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause()
        await click_row(pilot, "plan-titles", "Night Ferry")
        details = text_of(app, "#plan-details").splitlines()[0]
        stage = app.stage
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert stage is Stage.PLAN
    assert details == "Night Ferry"


async def test_a_click_on_a_queued_source_shows_its_path(tmp_path: Path) -> None:
    first = tv_backups(tmp_path, "First").resolve()
    second = tv_backups(tmp_path, "Second").resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, first, second)
        # The last Source queued is selected; the click goes to the first, on line 1.
        await pilot.click("#source-tree", offset=(4, 1))
        await pilot.pause()
        path = text_of(app, "#stage-lines").splitlines()[0].split(maxsplit=1)[1]
        # The "Queue" heading is no Source: a click there keeps a Source selected.
        await pilot.click("#source-tree", offset=(4, 0))
        await pilot.pause()
        lines = text_of(app, "#stage-lines").splitlines()

    assert path == str(first)
    assert lines and lines[0].split(maxsplit=1)[1] in (str(first), str(second))
