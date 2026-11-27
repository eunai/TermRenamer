"""The Plan Stage while the Plan is built: progress, the Title list, selection and cancel.

A stand-in Provider stops in each search until the test lets it go, so the test reads
the screen part-way through a build. The rate's clock is the test's own.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from textual.pilot import Pilot

from termrenamer.core.models import Candidate
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages import PlanStage
from termrenamer.tui.widgets.title_list import TitleList

from .screen_driver import (
    FERRY,
    SHOW,
    SIZE,
    make_app,
    names_in,
    press,
    queue,
    screen_text,
    text_of,
    tv_backups,
    until,
    wiring,
)


@dataclass
class PausingTv:
    """Answers like the screen driver's TV stand-in, but stops in each search.

    Each search sets ``waiting`` and stops until the test calls :meth:`let_go`. With
    ``paused`` off, searches answer at once.
    """

    paused: bool = True
    waiting: threading.Event = field(default_factory=threading.Event)
    _go: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(0))
    searches: list[str] = field(default_factory=list)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.searches.append(hint)
        if self.paused:
            self.waiting.set()
            self._go.acquire(timeout=10)
        shows = {"harbour lights": (SHOW,), "harbour lights uk": (SHOW,), "night ferry": (FERRY,)}
        return shows.get(hint.casefold(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return {
            ("11", 1, 1): "The Tide Comes In",
            ("11", 1, 2): "Salt and Rope",
            ("12", 1, 1): "Cast Off",
        }.get((show_id, season, episode))

    def let_go(self) -> None:
        self.waiting.clear()
        self._go.release()


class FixedClock:
    """A clock that only the test moves."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def _wait_in_search(pilot: Pilot[None], stand_in: PausingTv) -> None:
    assert await asyncio.to_thread(stand_in.waiting.wait, 5)
    await pilot.pause()


async def _start(
    pilot: Pilot[None], app: TermRenamerApp, stand_in: PausingTv, folder: Path
) -> FixedClock:
    """Queue ``folder`` and build, up to the second search (Night Ferry)."""
    clock = FixedClock()
    app.query_one(PlanStage).clock = clock
    await queue(pilot, folder)
    await press(pilot, "b")
    await _wait_in_search(pilot, stand_in)  # in Harbour Lights's search
    clock.now = 2.0
    stand_in.let_go()
    await _wait_in_search(pilot, stand_in)  # in Night Ferry's search
    return clock


async def _finish(pilot: Pilot[None], app: TermRenamerApp, stand_in: PausingTv) -> None:
    stand_in.paused = False
    stand_in.let_go()
    await app.workers.wait_for_complete()
    await pilot.pause()


STRIP_AT_TWO_OF_THREE = (
    "lookups ━━━━━━━━━━━━━━━━ 2/3 matched ███████████ 2 unmatched 0 lookups/s █ 1.0/s"
)


def _rows(app: TermRenamerApp) -> list[tuple[str, str, str]]:
    return [
        (row.name, str(row.status), row.count)
        for row in app.query_one(PlanStage).query_one(TitleList).rows
    ]


async def test_the_plan_stage_shows_how_far_the_build_is(tmp_path: Path) -> None:
    stand_in = PausingTv()
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await _start(pilot, app, stand_in, tv_backups(tmp_path))
        text = screen_text(app)
        rows = _rows(app)
        await _finish(pilot, app, stand_in)

    assert rows == [
        ("Harbour Lights", "found", "2"),
        ("Night Ferry", "looking up", "1"),
        ("holiday.mkv", "not recognised", "1"),
    ]
    assert "2 of 3 files looked up" in text
    assert "on TMDB…" in text
    assert "esc Cancel the Plan" in text
    [strip] = [line for line in text.splitlines() if line.startswith("lookups ")]
    # Two of three files matched, none unmatched; both looked up in the build's third
    # second, two seconds after it started.
    assert strip == STRIP_AT_TWO_OF_THREE


async def test_titles_wait_until_their_lookup_starts(tmp_path: Path) -> None:
    stand_in = PausingTv()
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        await _wait_in_search(pilot, stand_in)  # in Harbour Lights's search
        rows = _rows(app)
        text = screen_text(app)
        await _finish(pilot, app, stand_in)

    assert rows == [
        ("Harbour Lights", "looking up", "2"),
        ("Night Ferry", "waiting", "1"),
        ("holiday.mkv", "not recognised", "1"),
    ]
    assert "0 of 3 files looked up" in text


async def test_a_found_title_can_be_selected_during_the_build_and_shows_its_details(
    tmp_path: Path,
) -> None:
    stand_in = PausingTv()
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await _start(pilot, app, stand_in, tv_backups(tmp_path))
        await press(pilot, "down")
        looking_up = text_of(app, "#plan-details")
        await press(pilot, "up")
        found = text_of(app, "#plan-details")
        selected = app.query_one(PlanStage).query_one(TitleList).selected
        await _finish(pilot, app, stand_in)

    assert selected is not None and selected.name == "Harbour Lights"
    assert found.splitlines() == ["Harbour Lights", "found · 2 videos"]
    assert looking_up.splitlines() == ["Night Ferry", "looking up · 0 of 1 video looked up"]


async def test_escape_cancels_the_build_keeps_the_queue_and_renames_nothing(
    tmp_path: Path,
) -> None:
    stand_in = PausingTv()
    folder = tv_backups(tmp_path)
    before = names_in(tmp_path)
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await _start(pilot, app, stand_in, folder)
        await press(pilot, "escape")
        stage = app.stage
        message = text_of(app, "#message")
        locked = app.session_settings.locked
        await _finish(pilot, app, stand_in)
        assert app.stage is Stage.QUEUE
        assert app.plan is None
        assert app.queue.sources == (folder.resolve(),)
        assert text_of(app, "#message") == message
    assert stage is Stage.QUEUE
    assert message == "Plan cancelled. Nothing was renamed."
    assert not locked
    # Night Ferry's search was under way and finished; no lookup started after it.
    assert stand_in.searches == ["Harbour Lights", "Night Ferry"]
    assert names_in(tmp_path) == before


async def test_a_build_started_after_a_cancel_is_not_touched_by_the_cancelled_one(
    tmp_path: Path,
) -> None:
    stand_in = PausingTv()
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await _start(pilot, app, stand_in, tv_backups(tmp_path))
        await press(pilot, "escape")
        stand_in.paused = False
        await press(pilot, "b")
        for _ in range(200):
            if app.stage is Stage.PREVIEW:
                break
            await pilot.pause(0.01)
        plan = app.plan
        stand_in.let_go()  # the cancelled build's search answers now
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stage is Stage.PREVIEW
        assert app.plan is plan
        assert not app.session_settings.locked
        assert "Plan built" in text_of(app, "#message")
    assert plan is not None


async def test_two_titles_found_with_the_same_match_become_one_row(tmp_path: Path) -> None:
    stand_in = PausingTv(paused=False)
    folder = tv_backups(tmp_path)
    (folder / "Harbour Lights UK S02E01.mkv").write_bytes(b"x")
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await press(pilot, "b")
        await app.workers.wait_for_complete()
        await pilot.pause()
        rows = _rows(app)
        heading = text_of(app, "#plan-stage .list-count")

    assert rows == [
        ("Harbour Lights", "found", "3"),
        ("Night Ferry", "found", "1"),
        ("holiday.mkv", "not recognised", "1"),
    ]
    assert heading == "3"


async def test_a_selected_title_that_joins_another_keeps_the_selection_on_it(
    tmp_path: Path,
) -> None:
    stand_in = PausingTv()
    folder = tv_backups(tmp_path)
    (folder / "Aurora S01E01.mkv").write_bytes(b"x")
    (folder / "Harbour Lights UK S02E01.mkv").write_bytes(b"x")
    app = make_app(wiring(tv=stand_in))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await press(pilot, "b")
        await _wait_in_search(pilot, stand_in)  # in Aurora's search (not found)
        stand_in.let_go()
        await _wait_in_search(pilot, stand_in)  # in Harbour Lights's search
        stand_in.let_go()
        await _wait_in_search(pilot, stand_in)  # in Harbour Lights UK's search
        await press(pilot, "down", "down")
        stand_in.let_go()
        await _wait_in_search(pilot, stand_in)  # in Night Ferry's search
        selected = app.query_one(PlanStage).query_one(TitleList).selected
        details = text_of(app, "#plan-details")
        await _finish(pilot, app, stand_in)

    assert selected is not None and selected.name == "Harbour Lights"
    assert details.splitlines() == ["Harbour Lights", "found · 3 videos"]


async def test_while_the_first_scan_is_pending_no_zeroed_gauge_is_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.tui import app as screen  # noqa: PLC0415

    folder = tv_backups(tmp_path).resolve()
    go = threading.Event()
    started = threading.Event()
    planned = screen.plan_queue

    def held(*args: object, **kwargs: object) -> object:
        started.set()
        assert go.wait(timeout=10)
        return planned(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(screen, "plan_queue", held)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await press(pilot, "b")
        assert started.wait(timeout=5)
        await pilot.pause()
        pending = screen_text(app)
        go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert app.stage is Stage.PREVIEW
    assert "Reading the queued Sources…" in pending
    for zeroed in ("0 of 0 files", "0/0", "lookups/s", "matched", "unmatched"):
        assert zeroed not in pending, zeroed


@dataclass
class HeldFilms:
    """Film searches that each wait on ``go``, then find nothing."""

    started: threading.Event = field(default_factory=threading.Event)
    go: threading.Event = field(default_factory=threading.Event)
    searches: list[tuple[str, int | None]] = field(default_factory=list)

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append((hint, year))
        self.started.set()
        assert self.go.wait(timeout=10)
        return ()


async def test_escape_while_a_film_search_runs_sends_no_search_without_the_year(
    tmp_path: Path,
) -> None:
    """A Film search with a year that finds nothing is tried again without the year;
    after Escape, that second search is not sent."""
    folder = tmp_path / "Film Backups"
    folder.mkdir()
    (folder / "Heat (1995).mkv").write_bytes(b"x")
    films = HeldFilms()
    app = make_app(wiring(film=films))  # type: ignore[arg-type]
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder.resolve())
        await press(pilot, "b")
        await until(pilot, films.started.is_set)
        await press(pilot, "escape")
        films.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        stage = app.stage

    assert stage is Stage.QUEUE
    assert films.searches == [("Heat", 1995)]
