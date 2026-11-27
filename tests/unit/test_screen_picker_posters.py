"""The Match picker with Posters shown: the Candidates as picture tiles.

Posters are shown through a stand-in image widget and a stand-in image host (see
``screen_driver``); no request reaches a Provider or an image host.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from textual.pilot import Pilot

from termrenamer.core.models import Candidate
from termrenamer.persistence.posters import PosterRequest
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.dialogs.match_picker import CandidateTile, MatchPicker

from .screen_driver import (
    POSTERS_AVAILABLE,
    SIZE,
    ImageHost,
    StandInImage,
    build,
    make_app,
    press,
    queue,
    settings,
    text_of,
    tv_backups,
    wiring,
)
from .test_screen_pick_match import (
    HEAT_1986,
    HEAT_WAVE,
    LIGHTS_US,
    Films,
    film_preview,
    films,
    shows,
)

SMALLEST = (100, 35)
"""The smallest screen that shows Posters."""

IMAGES = "https://image.tmdb.org/t/p/w342"
HEAT_POSTER = Candidate(id="949", name="Heat", year=1995, poster_ref="/heat.jpg")
HEAT_1986_POSTER = Candidate(id="31", name="Heat", year=1986, poster_ref="/heat86.jpg")
HEAT_WAVE_POSTER = Candidate(id="77", name="Heat Wave", year=1990, poster_ref="/wave.jpg")


def poster_films() -> Films:
    """The films of the #28 tests, each with a Poster reference but Heat Wave's."""
    return Films(
        films={
            ("heat", 1995): (HEAT_POSTER, HEAT_1986_POSTER, HEAT_WAVE),
            ("heat wave", 1990): (HEAT_WAVE_POSTER,),
            ("heat", None): (HEAT_POSTER, HEAT_1986_POSTER),
            ("waves", None): (HEAT_WAVE, HEAT_POSTER),
        }
    )


def tiles_app(
    tmp_path: Path,
    host: ImageHost,
    *,
    show_posters: bool = True,
    film: Films | None = None,
) -> TermRenamerApp:
    store = host.store(tmp_path / "posters")
    wired = wiring(tv=shows(), film=film or films(), posters=store)
    app = make_app(wired, settings(show_posters=show_posters), posters=POSTERS_AVAILABLE)
    app.poster_store = store  # type: ignore[attr-defined]
    return app


@dataclass
class HoldingHost(ImageHost):
    """An image host whose answers for the ``held`` addresses wait until ``release``."""

    held: set[str] = field(default_factory=set)
    release: threading.Event = field(default_factory=threading.Event)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) in self.held:
            self.requests.append(request)
            assert self.release.wait(timeout=5)
            self.requests.pop()
        return super().handle(request)


async def until(pilot: Pilot[None], done: Callable[[], bool]) -> None:
    for _ in range(100):
        if done():
            return
        await pilot.pause(0.05)
    raise AssertionError("waited too long")


async def type_a_title(pilot: Pilot[None], text: str) -> None:
    await press(pilot, "slash")
    pilot.app.screen.query_one("#picker-typed").value = text  # type: ignore[attr-defined]
    await press(pilot, "enter")


async def film_picker(pilot: Pilot[None], tmp_path: Path) -> MatchPicker:
    await film_preview(pilot, tmp_path)
    await press(pilot, "t")
    await settle(pilot)
    assert isinstance(pilot.app.screen, MatchPicker)
    return pilot.app.screen


def selected_tile(app: TermRenamerApp) -> str | None:
    """The id of the one tile marked selected."""
    [tile] = [tile for tile in app.screen.query(".picker-tile.-selected") if tile.display]
    return tile.id


def tile(app: TermRenamerApp, index: int) -> CandidateTile:
    return app.screen.query_one(f"#picker-tile-{index}", CandidateTile)


def tile_images(app: TermRenamerApp, index: int) -> list[StandInImage]:
    return list(tile(app, index).query(StandInImage))


def tile_poster_words(app: TermRenamerApp, index: int) -> str:
    """The words drawn in a tile's picture in place of an image, without its dots."""
    view = tile(app, index).view
    drawn = str(view.text.render().plain).split()  # type: ignore[union-attr]
    return " ".join(word for word in drawn if word != "·")


def no_poster_lines(app: TermRenamerApp) -> list[str]:
    return [line for _n, line in app.log_book.lines_after(0) if "No Poster" in line]


async def open_picker(pilot: Pilot[None], tmp_path: Path) -> MatchPicker:
    await queue(pilot, tv_backups(tmp_path))
    await build(pilot)
    await press(pilot, "t")
    await settle(pilot)
    assert isinstance(pilot.app.screen, MatchPicker)
    return pilot.app.screen


async def settle(pilot: Pilot[None]) -> None:
    app = pilot.app
    await app.workers.wait_for_complete()
    for screen in app.screen_stack:
        await screen.workers.wait_for_complete()
    await pilot.pause()


def tile_words(app: TermRenamerApp) -> list[str]:
    """Each tile shown, as the lines under its picture: name, year, key."""
    shown = []
    for tile in app.screen.query(".picker-tile"):
        if tile.display:
            lines = [
                text_of(app, f"#{tile.id} {part}").strip()
                for part in (".tile-name", ".tile-year", ".tile-key")
            ]
            shown.append(" | ".join(lines))
    return shown


async def test_with_posters_shown_t_opens_the_current_match_the_next_candidate_and_type_a_title(
    tmp_path: Path,
) -> None:
    app = tiles_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, tmp_path)
        words = tile_words(app)
        rows = [row for row in app.screen.query("ChoiceRow") if row.display]
    assert words == [
        "Harbour Lights | (2019) (current) | 1",
        f"{LIGHTS_US.name} | ({LIGHTS_US.year}) | 2",
        "Type a title |  | /",
    ]
    assert rows == []


async def test_left_and_right_move_between_tiles_and_enter_uses_the_selected_one(
    tmp_path: Path,
) -> None:
    app = tiles_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        picker = await film_picker(pilot, tmp_path)
        assert picker.tiles is not None
        moves = [selected_tile(app)]
        for key in ("right", "right", "right", "left", "left", "left"):
            await press(pilot, key)
            moves.append(selected_tile(app))
        await press(pilot, "right", "enter")
        await settle(pilot)
        on_picker = isinstance(app.screen, MatchPicker)
        plan = app.plan

    first, second, typed = "picker-tile-0", "picker-tile-1", "picker-tile-type"
    assert moves == [first, second, typed, typed, second, first, first]
    assert not on_picker
    assert plan is not None and plan.titles[0].match == HEAT_1986


async def test_with_tiles_a_number_picks_and_escape_closes(tmp_path: Path) -> None:
    app = tiles_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        await film_picker(pilot, tmp_path)
        built = app.plan
        await press(pilot, "escape")
        closed = not isinstance(app.screen, MatchPicker)
        kept = app.plan
        await press(pilot, "t")
        await settle(pilot)
        await press(pilot, "2")
        await settle(pilot)
        picked = app.plan

    assert closed and kept is built
    assert picked is not None and picked.titles[0].match == HEAT_1986


async def test_with_tiles_slash_and_three_go_to_the_typing_field_in_the_third_tile(
    tmp_path: Path,
) -> None:
    app = tiles_app(tmp_path, ImageHost())
    async with app.run_test(size=SIZE) as pilot:
        picker = await film_picker(pilot, tmp_path)
        await press(pilot, "slash")
        typing_after_slash = picker.typing
        in_third_tile = picker.query_one("#picker-typed").parent.parent.id
        await press(pilot, "escape")
        await press(pilot, "t")
        await settle(pilot)
        await press(pilot, "3")
        picker = app.screen
        assert isinstance(picker, MatchPicker)
        typing_after_three = picker.typing
        await press(pilot, "left")  # moves the cursor in the field, not the selection
        still_typing = picker.typing

    assert typing_after_slash and typing_after_three and still_typing
    assert in_third_tile == "picker-tile-type"


async def test_each_candidate_tile_shows_its_poster_from_the_poster_store(tmp_path: Path) -> None:
    host = ImageHost()
    app = tiles_app(tmp_path, host, film=poster_films())
    async with app.run_test(size=SIZE) as pilot:
        await film_picker(pilot, tmp_path)
        drawn = [len(tile_images(app, index)) for index in (0, 1)]
        words = tile_words(app)
    # The current Match's Poster was stored for the main panel: drawn from disk.
    assert host.urls == [f"{IMAGES}/heat.jpg", f"{IMAGES}/heat86.jpg"]
    assert all(thread is not threading.main_thread() for thread in host.threads)
    assert drawn == [1, 1]
    assert words[:2] == ["Heat | (1995) (current) | 1", "Heat | (1986) | 2"]


async def test_a_candidate_with_no_poster_reference_shows_no_poster(tmp_path: Path) -> None:
    host = ImageHost()
    app = tiles_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, tmp_path)
        words = tile_poster_words(app, 1)
        drawn = tile_images(app, 1)
    assert words == f"{LIGHTS_US.name} no poster"
    assert drawn == []
    assert host.urls == [f"{IMAGES}/hl.jpg"]  # the main panel's only


async def test_a_failed_download_shows_no_poster_in_the_tile_and_logs_one_line(
    tmp_path: Path,
) -> None:
    host = ImageHost(status=404)
    app = tiles_app(tmp_path, host, film=poster_films())
    async with app.run_test(size=SIZE) as pilot:
        picker = await film_picker(pilot, tmp_path)
        words = [tile_poster_words(app, index) for index in (0, 1)]
        await press(pilot, "right", "left", "right")
        await settle(pilot)
        on_picker = app.screen is picker
        logs = no_poster_lines(app)
    assert words == ["Heat no poster", "Heat no poster"]
    assert on_picker
    # The main panel's failure is remembered: the current Match's tile asks no more.
    assert host.urls == [f"{IMAGES}/heat.jpg", f"{IMAGES}/heat86.jpg"]
    assert len(logs) == 2 and "heat86" not in logs[0]


def main_images(app: TermRenamerApp) -> list[StandInImage]:
    return list(app.screen_stack[0].query("#preview-poster StandInImage"))


async def test_while_the_picker_is_open_the_main_poster_is_blank_and_returns_when_it_closes(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = tiles_app(tmp_path, host)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        before = len(main_images(app))
        await press(pilot, "t")
        await settle(pilot)
        under_picker = len(main_images(app))
        in_tile = len(tile_images(app, 0))
        await press(pilot, "escape")
        await settle(pilot)
        after = len(main_images(app))
    assert (before, under_picker, after) == (1, 0, 1)
    assert in_tile == 1
    assert host.urls == [f"{IMAGES}/hl.jpg"]  # stored once, drawn from disk after


def stored(app: TermRenamerApp, ref: str) -> Path | None:
    assert app.plan is not None
    request = PosterRequest(app.plan.options.provider_id, ref)
    return app.poster_store.stored(request)  # type: ignore[attr-defined, no-any-return]


async def test_a_typed_search_replaces_the_tiles_candidates_and_their_posters(
    tmp_path: Path,
) -> None:
    host = ImageHost()
    app = tiles_app(tmp_path, host, film=poster_films())
    async with app.run_test(size=SIZE) as pilot:
        await film_picker(pilot, tmp_path)
        await type_a_title(pilot, "Heat Wave 1990")
        await settle(pilot)
        words = tile_words(app)
        [image] = tile_images(app, 1)
        await press(pilot, "2")
        await settle(pilot)
        plan = app.plan
    assert words[:2] == ["Heat | (1995) (current) | 1", "Heat Wave | (1990) | 2"]
    assert image.image == stored(app, "/wave.jpg")
    assert host.urls[-1] == f"{IMAGES}/wave.jpg"
    assert plan is not None and plan.titles[0].match == HEAT_WAVE_POSTER


async def test_a_late_poster_of_a_candidate_no_longer_shown_does_not_draw_over_the_new_one(
    tmp_path: Path,
) -> None:
    host = HoldingHost(held={f"{IMAGES}/heat86.jpg"})
    app = tiles_app(tmp_path, host, film=poster_films())
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        await press(pilot, "t")
        await until(pilot, lambda: f"{IMAGES}/heat86.jpg" in host.urls)
        await type_a_title(pilot, "Heat Wave 1990")
        await until(pilot, lambda: len(tile_images(app, 1)) == 1)
        host.release.set()
        await until(pilot, lambda: stored(app, "/heat86.jpg") is not None)
        await settle(pilot)
        images = tile_images(app, 1)
        words = tile_words(app)
    assert words[1] == "Heat Wave | (1990) | 2"
    assert [image.image for image in images] == [stored(app, "/wave.jpg")]


def list_rows(app: TermRenamerApp) -> list[str]:
    return [str(row.id) for row in app.screen.query("ChoiceRow") if row.display]


async def test_with_posters_hidden_the_picker_is_the_plain_list(tmp_path: Path) -> None:
    host = ImageHost()
    app = tiles_app(tmp_path, host, show_posters=False)
    async with app.run_test(size=SIZE) as pilot:
        picker = await open_picker(pilot, tmp_path)
        tiles = picker.tiles
        rows = list_rows(app)
        shown = tile_words(app)
    assert tiles is None
    assert rows == ["picker-choice-0", "picker-choice-1", "picker-type"]
    assert shown == []
    assert host.urls == []


@pytest.mark.parametrize("size", [(99, 35), (100, 34)])
async def test_below_the_size_for_posters_the_picker_is_the_plain_list(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    app = tiles_app(tmp_path, ImageHost())
    async with app.run_test(size=size) as pilot:
        picker = await open_picker(pilot, tmp_path)
        tiles = picker.tiles
        rows = list_rows(app)
    assert tiles is None
    assert len(rows) == 3


async def test_the_picker_changes_between_tiles_and_list_as_the_screen_is_resized(
    tmp_path: Path,
) -> None:
    app = tiles_app(tmp_path, ImageHost(), film=poster_films())
    async with app.run_test(size=SIZE) as pilot:
        picker = await film_picker(pilot, tmp_path)
        await press(pilot, "right")
        await press(pilot, "slash")
        picker.query_one("#picker-typed").value = "Heat Wa"  # type: ignore[attr-defined]
        await pilot.resize_terminal(90, 28)
        await settle(pilot)
        small = (picker.tiles, list_rows(app), picker.typing)
        typed_small = picker.query_one("#picker-typed").value  # type: ignore[attr-defined]
        await pilot.resize_terminal(*SIZE)
        await settle(pilot)
        large = (picker.tiles is not None, list_rows(app), picker.typing)
        typed_large = picker.query_one("#picker-typed").value  # type: ignore[attr-defined]
        drawn = len(tile_images(app, 1))
    assert small == (None, ["picker-choice-0", "picker-choice-1", "picker-type"], True)
    assert large == (True, [], True)
    assert typed_small == typed_large == "Heat Wa"
    assert drawn == 1


@pytest.mark.parametrize("size", [SIZE, SMALLEST])
async def test_every_tile_the_typing_field_the_status_and_the_hint_fit_beside_the_panel(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    provider = poster_films()
    provider.failing.add("broken")
    app = tiles_app(tmp_path, ImageHost(), film=provider)
    async with app.run_test(size=size) as pilot:
        picker = await film_picker(pilot, tmp_path)
        await type_a_title(pilot, "Broken")
        await settle(pilot)
        screen = picker.region
        dialog = picker.query_one("#picker-dialog").region
        panel = app.screen_stack[0].query_one("#preview-poster").region
        parts = {
            selector: picker.query_one(selector).region
            for selector in (
                "#picker-now",
                "#picker-tile-0",
                "#picker-tile-1",
                "#picker-tile-type",
                "#picker-typed",
                "#picker-status",
                "#picker-hint",
            )
        }
        frames = [frame.region for frame in picker.query(".tile-frame")]
        hint = text_of(app, "#picker-hint")
        status = text_of(app, "#picker-status")
    assert status == "TMDB answered 503: try again later. Nothing changed."
    assert not dialog.overlaps(panel)
    assert screen.contains_region(dialog)
    inside = dialog.shrink((1, 1, 1, 1))
    for selector, region in parts.items():
        assert region.area > 0, selector
        assert inside.contains_region(region), selector
    assert len(frames) == 3 and all(inside.contains_region(frame) for frame in frames)
    assert hint == "←→ choose · 1-3 or enter use it · / type a title · esc close"
