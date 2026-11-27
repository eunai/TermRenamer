"""Posters on the main screen: the framed panel on the Plan and Preview Stages.

Posters are unavailable by default, as on a plain install; tests that show them use a
stand-in image widget and a stand-in image host (see ``screen_driver``).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import Switch

from termrenamer.core.models import Candidate
from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.app import MIN_POSTER_SIZE, TermRenamerApp
from termrenamer.tui.dialogs import ApplyConfirm, UndoConfirm
from termrenamer.tui.dialogs.match_picker import MatchPicker
from termrenamer.tui.poster_support import NO_IMAGES, NOT_INSTALLED, PosterSupport
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages.preview import ROWS_FOR_POSTERS
from termrenamer.tui.views import HelpView, SettingsView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.footer import AppFooter
from termrenamer.tui.widgets.poster_panel import PosterPanel
from termrenamer.tui.widgets.title_details import TitleDetails

from .links import needs_symlinks, point_folder_at
from .screen_driver import (
    FERRY,
    POSTERS_AVAILABLE,
    POSTERS_UNREADABLE,
    SIZE,
    ImageHost,
    StandInImage,
    TvStandIn,
    build,
    long_season,
    make_app,
    mark_seen_walking,
    press,
    queue,
    screen_lines,
    screen_text,
    settings,
    text_of,
    tv_backups,
    tv_stand_in,
    until,
    wiring,
)
from .test_screen_text import MARKUP_NAME

HARBOUR_LIGHTS_POSTER = "https://image.tmdb.org/t/p/w342/hl.jpg"
SMALLEST = (100, ROWS_FOR_POSTERS)
"""The smallest screen that shows the poster panel."""
SHORT = (100, ROWS_FOR_POSTERS - 1)


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


async def test_why_posters_are_unavailable_is_shown_as_written(tmp_path: Path) -> None:
    # The reason can hold an import error's text: a Windows path, brackets, a $ word.
    reason = "cannot load C:\\Python\\[$accent]x[/]\\ [Group] $text \\"
    app = poster_app(tmp_path, ImageHost(), posters=PosterSupport(reason=reason))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "i")
        message = text_of(app, "#message")
        await press(pilot, "s")
        note = text_of(app, "#show-posters-note")
    assert message == f"Posters are unavailable: {reason}."
    assert note == f"Unavailable: {reason}."


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


@pytest.mark.parametrize("size", [SIZE, (100, ROWS_FOR_POSTERS)])
async def test_the_match_picker_does_not_cover_the_poster(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=size) as pilot:
        await built(pilot, tmp_path)
        frame: Region = panel(app).region
        drawn_before = frame_column(app)
        await press(pilot, "t")
        await pilot.pause()
        assert isinstance(app.screen, MatchPicker)
        dialog = app.screen.query_one("#picker-dialog").region
        drawn_under = frame_column(app)
        words = panel_text(app)
    assert dialog.area > 0
    assert not frame.overlaps(dialog)
    assert drawn_before == drawn_under == frame.x
    assert "Harbour Lights" in words  # the name, in place of the image


async def test_without_the_panel_the_match_picker_is_centred(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost(), show_posters=False)
    async with app.run_test(size=SMALLEST) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "t")
        await pilot.pause()
        dialog = app.screen.query_one("#picker-dialog").region
    assert abs(dialog.x - (SMALLEST[0] - dialog.right)) <= 1


@pytest.mark.parametrize("size", [SIZE, (100, ROWS_FOR_POSTERS)])
async def test_the_apply_confirm_does_not_cover_the_poster(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=size) as pilot:
        await built(pilot, tmp_path)
        frame: Region = panel(app).region
        drawn_before = frame_column(app)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        dialog = app.screen.query_one("#confirm-dialog").region
        drawn_under = frame_column(app)
    assert not frame.overlaps(dialog)
    assert drawn_before == drawn_under == frame.x


def frame_column(app: TermRenamerApp) -> int:
    """The column the panel's top border is drawn at."""
    [row] = [line for line in screen_lines(app) if "┌─ TMDB" in line]
    return row.index("┌─ TMDB")


async def test_while_the_apply_confirm_is_open_the_panel_shows_the_name_not_the_image(
    tmp_path: Path,
) -> None:
    # The confirm's backdrop tints what lies under it, which breaks a Kitty image.
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        under_dialog = (images(app), panel_text(app))
        await press(pilot, "n")
        await pilot.pause()
        after = len(images(app))
    assert under_dialog[0] == []
    assert "Harbour Lights" in under_dialog[1]
    assert after == 1


async def test_a_discarded_preview_downloads_nothing_when_posters_are_turned_on(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host, show_posters=False)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "escape")
        assert app.stage is Stage.QUEUE
        await press(pilot, "i")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert host.requests == []


async def test_a_poster_file_the_image_widget_cannot_read_shows_no_poster(
    tmp_path: Path,
) -> None:
    app = poster_app(tmp_path, ImageHost(), posters=POSTERS_UNREADABLE)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await pilot.pause()
        words = panel_text(app)
        drawn = images(app)
        logs = [line for _n, line in app.log_book.lines_after(0) if "No Poster" in line]
    assert "Harbour Lights" in words and "no poster" in words
    assert drawn == []
    assert len(logs) == 1


def poster_logs(app: TermRenamerApp) -> list[str]:
    return [line for _n, line in app.log_book.lines_after(0) if "No Poster" in line]


async def test_a_failed_download_is_remembered_even_when_its_view_went_away(
    tmp_path: Path,
) -> None:
    # The download's outcome belongs to the download: the screen shrinks below the
    # size for Posters while the answer is on its way, so the panel goes, and the 404
    # still counts once; the panel back does not ask again.
    gate = threading.Event()
    host = ImageHost(status=404, gate=gate)
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        await until(pilot, lambda: bool(host.requests))
        assert app.stage is Stage.PREVIEW and len(host.requests) == 1
        await pilot.resize_terminal(90, 28)
        await pilot.pause(0.2)
        assert not panel(app).display
        gate.set()
        await until(pilot, lambda: bool(poster_logs(app)))
        await pilot.resize_terminal(*SIZE)
        await pilot.pause(0.3)
        words = panel_text(app)
        logs = poster_logs(app)
    assert len(host.requests) == 1
    assert "no poster" in words
    assert len(logs) == 1 and "HTTP 404" in logs[0]


async def test_an_abandoned_download_is_tried_again_when_the_title_is_selected_again(
    tmp_path: Path,
) -> None:
    # The first answer is a 503; nobody wants the Poster by then, so the download is
    # given up before a second attempt, records nothing, and starts anew later.
    gate = threading.Event()
    host = ImageHost(status=503, gate=gate, attempts=2)
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        await until(pilot, lambda: bool(host.requests))
        await press(pilot, "down")  # Night Ferry, which has no Poster
        gate.set()
        await pilot.pause(0.3)
        after_release = (len(host.requests), poster_logs(app))
        await press(pilot, "up")
        await until(pilot, lambda: "no poster" in panel_text(app))
        logs = poster_logs(app)
    assert after_release == (1, [])
    assert len(host.requests) == 3  # tried again: two attempts, both 503
    assert len(logs) == 1 and "503" in logs[0]


async def test_hiding_posters_during_a_download_starts_no_new_attempt(tmp_path: Path) -> None:
    gate = threading.Event()
    host = ImageHost(status=503, gate=gate, attempts=2)
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        await until(pilot, lambda: bool(host.requests))
        await press(pilot, "i")
        gate.set()
        await pilot.pause(0.3)
        while_hidden = len(host.requests)
        await press(pilot, "i")
        await until(pilot, lambda: "no poster" in panel_text(app))
        tried_again = len(host.requests)
    assert while_hidden == 1
    assert tried_again == 3  # shown again: a new download, two attempts


async def test_a_poster_folder_that_is_a_link_shows_no_poster_and_logs_one_line(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    point_folder_at(tmp_path / "posters", elsewhere)
    host = ImageHost()
    app = poster_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
        await pilot.pause(0.2)
        words = panel_text(app)
        logs = [
            line
            for _n, line in app.log_book.lines_after(0)
            if "No Poster" in line or "Posters are not stored" in line
        ]
    assert "no poster" in words
    assert host.requests == []
    assert list(elsewhere.iterdir()) == []
    assert len(logs) == 1 and "poster folder" in logs[0]


async def test_a_stored_poster_that_is_a_link_is_not_drawn_and_is_downloaded_again(
    tmp_path: Path,
) -> None:
    """A link at a stored Poster's name, pointing outside the poster folder, is never
    taken for the Poster: it is downloaded again into the folder, and the file the link
    pointed to is left as it was."""
    needs_symlinks(tmp_path)
    store = tmp_path / "posters"
    first = ImageHost()
    app = poster_app(tmp_path, first)
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, tmp_path)
    (stored,) = [path for path in store.iterdir() if path.is_file()]
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not the poster")
    stored.unlink()
    stored.symlink_to(outside)

    again = ImageHost()
    app = poster_app(tmp_path, again)
    later = tmp_path / "later"
    later.mkdir()
    async with app.run_test(size=SIZE) as pilot:
        await built(pilot, later)
        await app.workers.wait_for_complete()
        await pilot.pause()
        drawn = [image.image for image in images(app)]

    assert again.urls == [HARBOUR_LIGHTS_POSTER]
    assert drawn == [stored]
    assert not stored.is_symlink()
    assert outside.read_bytes() == b"not the poster"


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


async def test_below_100_columns_or_the_rows_for_posters_the_panel_is_hidden(
    tmp_path: Path,
) -> None:
    for size in ((99, ROWS_FOR_POSTERS), SHORT):
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


def test_posters_need_100_columns_and_35_rows_as_the_readme_says() -> None:
    assert MIN_POSTER_SIZE == (100, ROWS_FOR_POSTERS) == (100, 35)


async def test_at_the_smallest_size_the_details_and_actions_fit_under_the_panel(
    tmp_path: Path,
) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SMALLEST) as pilot:
        await built(pilot, tmp_path)
        shown = panel(app).display
        scroll = app.query_one("#details-scroll")
        overflow = scroll.max_scroll_y
        details = app.query_one(TitleDetails).region
        column = app.query_one("#details").region
        footer = app.query_one(AppFooter).region
        leave_out = app.query_one("#leave-out").region
        apply = [b.region for b in app.query(ActionButton) if b.press_key == "enter"]
        on_screen = screen_text(app)
        panel_bottom = panel(app).region.bottom
        [name_row] = [line for line in screen_lines(app) if line.startswith("   Harbour Lights ")]
    assert shown
    assert overflow == 0  # the compact details fit their scroll whole
    assert details.y >= panel_bottom
    assert "Harbour Lights" in on_screen and "ready · 1 season · 2 videos" in on_screen
    assert "S01" in on_screen and "▔▔" in on_screen
    assert name_row.index("Harbour Lights") == 3  # under the panel's left edge
    assert column.contains_region(leave_out) and leave_out.bottom <= footer.y
    assert [r for r in apply if r.area > 0 and r.bottom <= footer.y]


async def test_at_the_smallest_size_change_match_and_leave_out_both_fit(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SMALLEST) as pilot:
        await built(pilot, tmp_path)
        both = [app.query_one(f"#{name}").display for name in ("change-match", "leave-out")]
        overflow = app.query_one("#details-scroll").max_scroll_y
        footer = app.query_one(AppFooter).region
        buttons = [app.query_one(f"#{name}").region for name in ("change-match", "leave-out")]
    assert both == [True, True]
    assert overflow == 0
    assert all(b.height == 1 and b.bottom <= footer.y for b in buttons)
    assert buttons[0].bottom <= buttons[1].y


async def test_at_the_smallest_size_the_selected_file_stays_in_view(tmp_path: Path) -> None:
    folder, tv = long_season(tmp_path, 13)
    host = ImageHost()
    app = make_app(
        wiring(tv=tv, posters=host.store(tmp_path / "posters")),
        settings(),
        posters=POSTERS_AVAILABLE,
    )
    async with app.run_test(size=SMALLEST) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        shown = panel(app).display
        overflow = app.query_one("#details-scroll").max_scroll_y
        seen = await mark_seen_walking(pilot, 13)
    assert shown
    assert overflow > 0  # the cells wrap past the scroll
    assert seen == "y" * 24


async def test_one_row_short_the_preview_looks_as_with_posters_off(tmp_path: Path) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=SHORT) as pilot:
        await built(pilot, tmp_path)
        layout = (
            panel(app).display,
            app.query_one("#preview-summary").display,
            app.query_one("#summary-under").display,
            app.stage_view.has_class("-posters"),
        )
    assert layout == (False, True, False, False)


async def test_at_the_smallest_size_the_plan_stage_shows_its_details(tmp_path: Path) -> None:
    host = ImageHost()
    app = poster_app(tmp_path, host, hold=True)
    tv = app.tv_stand_in  # type: ignore[attr-defined]
    async with app.run_test(size=SMALLEST) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        shown = panel(app, "#plan-poster").display
        details = app.query_one("#plan-details").region
        footer = app.query_one(AppFooter).region
        on_screen = screen_text(app)
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert shown
    assert details.height > 0 and details.bottom <= footer.y
    assert "found · 2 videos" in on_screen


async def test_the_confirm_moves_beside_the_panel_when_the_screen_grows(
    tmp_path: Path,
) -> None:
    app = poster_app(tmp_path, ImageHost())
    async with app.run_test(size=(99, ROWS_FOR_POSTERS)) as pilot:
        await built(pilot, tmp_path)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        await pilot.resize_terminal(*SMALLEST)
        await pilot.pause(0.1)
        dialog = app.screen.query_one("#confirm-dialog").region
        frame = panel(app).region
        drawn = frame_column(app)
        shown = panel(app).display
    assert shown
    assert not frame.overlaps(dialog)
    assert drawn == frame.x


async def test_i_says_the_size_posters_need_when_the_screen_is_too_small(
    tmp_path: Path,
) -> None:
    app = poster_app(tmp_path, ImageHost(), show_posters=False)
    async with app.run_test(size=SHORT) as pilot:
        await press(pilot, "i")
        message = text_of(app, "#message")
        await press(pilot, "s")
        note = text_of(app, "#show-posters-note")
    assert message == "Posters on. They show when the screen is at least 100 columns by 35 rows."
    assert note == "Posters show when the screen is at least 100 columns by 35 rows."


async def test_an_unreadable_poster_logs_one_line_across_the_plan_and_preview(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    store = host.store(tmp_path / "posters")
    store.fetch(PosterRequest("tmdb", "/hl.jpg"))
    tv = tv_stand_in(hold=True)
    app = make_app(wiring(tv=tv, posters=store), settings(), posters=POSTERS_UNREADABLE)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        plan_words = panel_text(app, "#plan-poster")
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        preview_words = panel_text(app)
        logs = [line for _n, line in app.log_book.lines_after(0) if "No Poster" in line]
    assert "no poster" in plan_words and "no poster" in preview_words
    assert len(logs) == 1


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


def panel_box(app: TermRenamerApp) -> list[str]:
    """The poster panel's rows as the screen draws them, its frame included: the rows
    from the top border, which holds the Provider's name, to the bottom one."""
    lines = screen_lines(app)
    (top,) = [n for n, line in enumerate(lines) if "┌─ " in line]
    left = lines[top].index("┌")
    right = lines[top].index("┐", left)
    bottom = min(n for n in range(top + 1, len(lines)) if lines[n][left] == "└")
    return [line[left : right + 1] for line in lines[top : bottom + 1]]


def assert_framed(box: list[str], provider: str) -> None:
    """The frame is whole: the Provider's name on the top border, a side on each row."""
    width = len(box[0])
    assert box[0] == f"┌─ {provider} ".ljust(width - 1, "─") + "┐"
    assert all(row[0] == "│" and row[-1] == "│" for row in box[1:-1])
    assert box[-1] == "└" + "─" * (width - 2) + "┘"


@pytest.mark.parametrize(
    "name", ["C:\\Films\\", "[b]Bold[/b] \\", "A name [/]", "[$accent]x $text", MARKUP_NAME]
)
async def test_the_panel_draws_a_match_name_as_written_inside_its_whole_frame(
    tmp_path: Path, name: str
) -> None:
    # The Match name is the Provider's text, so it can read as markup or end in a backslash,
    # which would escape a closing tag after it. The border's Provider name is the app's own.
    tv = TvStandIn(
        shows={
            "harbour lights": (Candidate(id="11", name=name, year=2019),),
            "night ferry": (FERRY,),
        },
        episodes={("11", 1, 1): "The Tide Comes In", ("11", 1, 2): "Salt and Rope"},
        hold=True,
    )
    app = make_app(
        wiring(tv=tv, posters=ImageHost().store(tmp_path / "posters")),
        settings(),
        posters=POSTERS_AVAILABLE,
    )
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause(0.2)
        building = app.stage
        on_plan = panel_box(app)
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        on_preview = panel_box(app)
    # A name wider than the panel is cut, with an ellipsis.
    inner = len(on_plan[0]) - 2
    shown = name if len(name) <= inner - 2 else name[: inner - 3] + "…"
    assert building is Stage.PLAN
    for box in (on_plan, on_preview):
        assert_framed(box, "TMDB")
        rows = [row[1:-1] for row in box[1:-1]]
        named = [n for n, row in enumerate(rows) if f" {shown} " in row]
        assert len(named) == 1, box
        assert "no poster" in rows[named[0] + 1]


async def test_on_the_applied_stage_the_undo_confirm_keeps_its_own_place(tmp_path: Path) -> None:
    # No panel shows on the Applied Stage, so a confirm there is not moved right of one.
    places = []
    for show in (True, False):
        parent = tmp_path / str(show)
        parent.mkdir()
        folder = tv_backups(parent)
        app = make_app(
            wiring(tv=tv_stand_in(), posters=ImageHost().store(tmp_path / f"p{show}")),
            settings(show_posters=show, folder_rename=True, season_folders=True),
            posters=POSTERS_AVAILABLE,
        )
        async with app.run_test(size=SMALLEST) as pilot:
            await queue(pilot, folder)
            await build(pilot)
            await press(pilot, "enter", "y")
            await app.workers.wait_for_complete()
            await press(pilot, "u")
            await pilot.pause()
            assert isinstance(app.screen, UndoConfirm)
            places.append(app.screen.query_one("#confirm-dialog").region)
    assert places[0] == places[1]
