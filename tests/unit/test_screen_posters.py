"""Posters on the main screen: the framed panel on the Plan and Preview Stages.

Posters are unavailable by default, as on a plain install; tests that show them use a
stand-in image widget and a stand-in image host (see ``screen_driver``).
"""

from __future__ import annotations

import threading
from pathlib import Path

from textual.geometry import Region
from textual.widgets import Switch

from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.poster_support import NO_IMAGES, NOT_INSTALLED, PosterSupport
from termrenamer.tui.stage import Stage
from termrenamer.tui.views import HelpView, SettingsView
from termrenamer.tui.widgets.poster_panel import PosterPanel
from termrenamer.tui.widgets.title_details import TitleDetails

from .screen_driver import (
    POSTERS_AVAILABLE,
    SIZE,
    ImageHost,
    StandInImage,
    build,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
    tv_stand_in,
    wiring,
)

HARBOUR_LIGHTS_POSTER = "https://image.tmdb.org/t/p/w342/hl.jpg"


def poster_app(
    tmp_path: Path,
    host: ImageHost,
    *,
    posters: PosterSupport | None = POSTERS_AVAILABLE,
    show_posters: bool = True,
    hold: bool = False,
) -> TermRenamerApp:
    tv = tv_stand_in(hold=hold)
    wired = wiring(tv=tv, posters=host.store(tmp_path / "posters"))
    app = make_app(wired, settings(show_posters=show_posters), posters=posters)
    app.tv_stand_in = tv  # type: ignore[attr-defined]
    return app


def panel(app: TermRenamerApp, stage: str = "#preview-poster") -> PosterPanel:
    return app.screen_stack[0].query_one(stage, PosterPanel)


def images(app: TermRenamerApp) -> list[StandInImage]:
    return list(app.screen_stack[0].query(StandInImage))


def panel_text(app: TermRenamerApp, stage: str = "#preview-poster") -> str:
    view = panel(app, stage).view
    return " ".join(str(view.text.render().plain).split())  # type: ignore[union-attr]


async def built(pilot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    await queue(pilot, tv_backups(tmp_path))
    await build(pilot)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


# ------------------------------------------------------------ unavailable


async def test_without_posters_the_panel_is_hidden_and_nothing_is_downloaded(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host, posters=PosterSupport(reason=NOT_INSTALLED))
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "down")
        await app.workers.wait_for_complete()
        shown = panel(app).display
        summary_left = app.query_one("#preview-summary").display
        drawn = images(app)
    assert not shown
    assert summary_left
    assert host.requests == []
    assert drawn == []


async def test_i_says_why_posters_are_unavailable(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost(), posters=PosterSupport(reason=NO_IMAGES))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "i")
        message = text_of(app, "#message")
        still_on = app.session_settings.show_posters
    assert message == f"Posters are unavailable: {NO_IMAGES}."
    assert still_on


async def test_settings_shows_posters_unavailable_with_the_reason(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost(), posters=PosterSupport(reason=NOT_INSTALLED))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        assert isinstance(app.screen, SettingsView)
        value = text_of(app, "#show-posters-value")
        note = text_of(app, "#show-posters-note")
        disabled = app.screen.query_one("#show-posters", Switch).disabled
    assert value == "unavailable"
    assert note == f"Unavailable: {NOT_INSTALLED}."
    assert disabled


# ---------------------------------------------------------------- shown


async def test_the_preview_shows_the_selected_titles_poster_in_the_framed_panel(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        frame = panel(app)
        title = frame.border_title
        region = frame.region
        shown = images(app)
        on_screen = screen_text(app)
    assert host.urls == [HARBOUR_LIGHTS_POSTER]
    assert all(thread is not threading.main_thread() for thread in host.threads)
    assert title == "TMDB"
    assert (region.width, region.height) == (26, 19)
    assert len(shown) == 1
    assert "POSTER" in on_screen


async def test_a_title_with_no_poster_reference_shows_its_name_and_no_poster(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "down")
        await app.workers.wait_for_complete()
        await pilot.pause()
        words = panel_text(app)
        shown = images(app)
    assert "Night Ferry" in words and "no poster" in words
    assert shown == []
    assert host.urls == [HARBOUR_LIGHTS_POSTER]


async def test_a_poster_seen_before_is_drawn_from_disk(tmp_path: Path) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "down")
        await press(pilot, "up")
        await app.workers.wait_for_complete()
        await pilot.pause()
        shown = images(app)
    assert len(shown) == 1
    assert host.urls == [HARBOUR_LIGHTS_POSTER]


async def test_a_failed_download_shows_no_poster_and_logs_one_line(tmp_path: Path) -> None:
    host = ImageHost(status=404)
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await pilot.pause()
        words = panel_text(app)
        stage = app.stage
        logs = [line for _n, line in app.log_book.lines_after(0) if "No Poster" in line]
    assert "Harbour Lights" in words and "no poster" in words
    assert stage is Stage.PREVIEW
    assert len(logs) == 1 and "Harbour Lights" in logs[0]


async def test_the_summary_and_apply_sit_under_the_title_list_beside_the_poster(
    tmp_path: Path,
) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        under = app.query_one("#summary-under")
        left = app.query_one("#preview-summary")
        titles = app.query_one("#preview-titles")
        frame = panel(app)
        layout = (under.display, left.display)
        below_list = under.region.y >= titles.region.bottom
        right_of_panel = under.region.x >= frame.region.right
        counts = text_of(app, "#summary-counts-under")
    assert layout == (True, False)
    assert below_list and right_of_panel
    assert "ready" in counts


async def test_the_poster_is_fixed_outside_the_scrolling_details(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        frame = panel(app)
        scroll = app.query_one("#details-scroll")
        ancestors = list(frame.ancestors)
        details = app.query_one(TitleDetails)
        under_panel = details.region.y > frame.region.bottom
    assert scroll not in ancestors
    assert under_panel


async def test_the_apply_confirm_does_not_cover_the_poster(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        frame: Region = panel(app).region
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        dialog = app.screen.query_one("#confirm-dialog").region
    assert not frame.overlaps(dialog)


# ------------------------------------------------------------ hiding them


async def test_i_hides_the_panel_removes_the_image_and_the_details_move_up(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        below_poster = app.query_one(TitleDetails).region.y
        await press(pilot, "i")
        message = text_of(app, "#message")
        hidden = not panel(app).display
        left_images = images(app)
        moved_up = app.query_one(TitleDetails).region.y < below_poster
        summary = (
            app.query_one("#preview-summary").display,
            app.query_one("#summary-under").display,
        )
        await press(pilot, "i")
        await app.workers.wait_for_complete()
        await pilot.pause()
        back = (panel(app).display, len(images(app)), text_of(app, "#message"))
    assert message == "Posters hidden (i shows them)."
    assert hidden and left_images == [] and moved_up
    assert summary == (True, False)
    assert back == (True, 1, "Posters shown.")
    assert host.urls == [HARBOUR_LIGHTS_POSTER]


async def test_nothing_is_downloaded_while_posters_are_hidden(tmp_path: Path) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host, show_posters=False)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "down")
        await press(pilot, "up")
        await app.workers.wait_for_complete()
        hidden = host.requests == [] and not panel(app).display
        await press(pilot, "i")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert hidden
    assert host.urls == [HARBOUR_LIGHTS_POSTER]


async def test_the_settings_row_shows_and_hides_posters(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "s")
        switch = app.screen.query_one("#show-posters", Switch)
        before = (switch.value, text_of(app, "#show-posters-value"))
        switch.value = False
        await pilot.pause()
        after = (text_of(app, "#show-posters-value"), text_of(app, "#settings-message"))
        await press(pilot, "escape")
        hidden = not panel(app).display
        stage = app.stage
    assert before == (True, "on")
    assert after == ("off", "Show posters: off.")
    assert hidden
    assert stage is Stage.PREVIEW


async def test_i_in_settings_changes_the_row(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "s")
        app.screen.query_one("#show-posters", Switch).focus()
        await press(pilot, "i")
        value = text_of(app, "#show-posters-value")
    assert value == "off"
    assert app.session_settings.show_posters is False


async def test_below_100_columns_or_30_rows_the_panel_is_hidden(tmp_path: Path) -> None:
    for size in ((99, 36), (120, 29)):
        host = ImageHost()
        app = poster_app(tmp_path / f"{size[0]}x{size[1]}", host)
        (tmp_path / f"{size[0]}x{size[1]}").mkdir()
        async with app.run_test(size=size) as pilot:
            await built(pilot, tmp_path / f"{size[0]}x{size[1]}")
            hidden = (not panel(app).display, app.query_one("#preview-summary").display)
            nothing = host.requests == []
            await pilot.resize_terminal(*SIZE)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            shown = panel(app).display
        assert hidden == (True, True), size
        assert nothing, size
        assert shown, size
        assert host.urls == [HARBOUR_LIGHTS_POSTER], size


# ------------------------------------------------------------- the build


async def test_no_poster_is_downloaded_while_the_plan_is_built(tmp_path: Path) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host, hold=True)
    tv = app.tv_stand_in  # type: ignore[attr-defined]
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        building = app.stage
        shown = panel(app, "#plan-poster").display
        words = panel_text(app, "#plan-poster")
        during = list(host.requests)
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert building is Stage.PLAN
    assert shown
    assert "Harbour Lights" in words and "found" in words
    assert during == []
    assert host.urls == [HARBOUR_LIGHTS_POSTER]


async def test_the_plan_stage_draws_a_stored_poster(tmp_path: Path) -> None:
    host = ImageHost()
    store = host.store(tmp_path / "posters")
    store.fetch(PosterRequest("tmdb", "/hl.jpg"))
    tv = tv_stand_in(hold=True)
    app = make_app(wiring(tv=tv, posters=store), settings(), posters=POSTERS_AVAILABLE)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        drawn = [image.image for image in images(app)]
        title = panel(app, "#plan-poster").border_title
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert drawn == [store.stored(PosterRequest("tmdb", "/hl.jpg"))]
    assert title == "TMDB"
    assert len(host.requests) == 1


# ------------------------------------------------------------------ Help


async def test_help_shows_the_provider_credits() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "?")
        assert isinstance(app.screen, HelpView)
        text = " ".join(text_of(app, "#help-body").split())
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in text
    assert "Metadata provided by TheTVDB." in text
    assert "https://thetvdb.com/" in text
