"""The key table at each Stage: Mode, Provider, the lock while a Plan is built, and old keys."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from termrenamer.core.models import ScanMode
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages import PreviewStage
from termrenamer.tui.views import SettingsView
from termrenamer.tui.widgets.title_list import TitleList

from .screen_driver import (
    SIZE,
    build,
    film_stand_in,
    footer_keys,
    make_app,
    press,
    queue,
    screen_text,
    text_of,
    tv_backups,
    tv_stand_in,
    wiring,
)


async def test_m_changes_the_mode_and_p_steps_through_its_providers() -> None:
    app = make_app(wiring(tvdb=tv_stand_in(), omdb=film_stand_in()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        owner = app.session_settings
        assert (owner.mode, owner.provider_id) == (ScanMode.TV, "tmdb")
        await press(pilot, "p")
        assert owner.provider_id == "tvdb"
        assert "Provider TheTVDB" in screen_text(app)
        await press(pilot, "p")
        assert owner.provider_id == "tmdb"
        await press(pilot, "m")
        assert (owner.mode, owner.provider_id) == (ScanMode.FILM, "tmdb")
        await press(pilot, "p")
        assert owner.provider_id == "omdb"
        assert "Provider OMDb" in screen_text(app)


async def test_a_change_of_mode_picks_the_first_provider_with_a_key() -> None:
    app = make_app(wiring(tmdb=False, tvdb=tv_stand_in()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        owner = app.session_settings
        assert owner.provider_id == "tvdb"
        await press(pilot, "m")
        assert (owner.mode, owner.provider_id) == (ScanMode.FILM, "tmdb")
        assert "Provider TMDB (no key)" in screen_text(app)


async def test_m_or_p_at_the_preview_discards_the_plan_with_a_message(tmp_path: Path) -> None:
    app = make_app(wiring(tvdb=tv_stand_in()))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        for key in ("m", "p"):
            await build(pilot)
            assert app.stage is Stage.PREVIEW
            await press(pilot, key)
            assert app.stage is Stage.QUEUE
            assert app.plan is None
            assert len(app.queue.sources) == 1
            assert "Plan discarded" in text_of(app, "#message")
            if key == "m":
                await press(pilot, "m")


async def test_settings_mode_and_provider_are_refused_while_the_plan_is_built(
    tmp_path: Path,
) -> None:
    stand_in = tv_stand_in(hold=True)
    app = make_app(wiring(tv=stand_in))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert await asyncio.to_thread(stand_in.first_done.wait, 5)
        messages = []
        for key in ("s", "m", "p"):
            await press(pilot, key)
            messages.append(text_of(app, "#message"))
        still_tv = app.session_settings.mode is ScanMode.TV
        no_settings = not isinstance(app.screen, SettingsView)
        stand_in.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert still_tv and no_settings
    assert messages == [
        "Settings cannot change while a Plan is being built or applied.",
        "Mode cannot change while a Plan is being built or applied.",
        "Provider cannot change while a Plan is being built or applied.",
    ]


async def test_sources_are_added_or_cleared_only_at_the_queue_stage(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        for key in ("a", "f", "c"):
            await press(pilot, key)
            assert app.screen is app.screen_stack[0]
            assert app.queue.sources == (folder.resolve(),)
            assert "works at the Queue Stage" in text_of(app, "#message")
        keys = footer_keys(app)
    assert not any(key.startswith(("a ", "f ", "c ", "b ")) for key in keys)
    assert "enter Apply…" in keys and "esc Discard Plan" in keys


@pytest.mark.parametrize("key", ["ctrl+f", "ctrl+comma", "f1", "ctrl+p"])
async def test_the_removed_keys_do_nothing(key: str) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, key)
        assert app.screen is app.screen_stack[0]
        assert app.is_running
        assert app.stage is Stage.QUEUE


async def test_q_quits() -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "q")
        assert not app.is_running


async def test_a_film_title_shows_its_year_at_the_preview(tmp_path: Path) -> None:
    folder = tmp_path / "Film Backups"
    folder.mkdir()
    (folder / "Metropolis (1927).mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        rows = [
            (r.name, r.status, r.count)
            for r in app.query_one(PreviewStage).query_one(TitleList).rows
        ]
    assert rows == [("Metropolis (1927)", "ready", "1")]


async def test_a_title_the_provider_does_not_find_is_a_no_match_row(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    (folder / "Lost Signal S01E01.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        rows = [
            (r.name, r.status, r.count)
            for r in app.query_one(PreviewStage).query_one(TitleList).rows
        ]
    assert rows == [("Lost Signal", "no match", "1")]


@pytest.mark.parametrize("size", [(80, 24), (90, 28), (99, 29)])
async def test_the_screen_works_below_100_columns_or_30_rows(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=size) as pilot:
        assert "Nothing queued yet" in screen_text(app)
        await queue(pilot, folder)
        await build(pilot)
        text = screen_text(app)
        assert "Harbour Lights" in text and "holiday.mkv" in text
        assert "enter Apply" in text
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "3 renamed" in screen_text(app)


async def test_with_only_a_tvdb_key_a_tv_plan_is_built_with_thetvdb(tmp_path: Path) -> None:
    stand_in = tv_stand_in()
    app = make_app(wiring(tmdb=False, tvdb=stand_in))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        assert app.plan is not None
        assert app.plan.options.provider_id == "tvdb"
    assert stand_in.searches == ["Harbour Lights", "Night Ferry"]


@pytest.mark.parametrize(
    ("mode_presses", "provider_presses", "message"),
    [
        (0, 0, "TMDB requires an API key"),
        (0, 1, "TheTVDB requires an API key"),
        (1, 1, "OMDb requires an API key"),
    ],
)
async def test_building_with_a_provider_that_has_no_key_gives_its_message_and_no_plan(
    tmp_path: Path, mode_presses: int, provider_presses: int, message: str
) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    (folder / "Harbour Lights S01E01.mkv").write_bytes(b"x")
    (folder / "Metropolis (1927).mkv").write_bytes(b"x")
    app = make_app(wiring(tmdb=mode_presses + provider_presses == 2))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, *(["m"] * mode_presses), *(["p"] * provider_presses))
        await queue(pilot, folder)
        await build(pilot)
        assert app.plan is None
        assert app.stage is Stage.QUEUE
        assert message in text_of(app, "#message")


async def test_escape_while_the_plan_is_built_gives_no_message_about_another_stage(
    tmp_path: Path,
) -> None:
    stand_in = tv_stand_in(hold=True)
    app = make_app(wiring(tv=stand_in))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert await asyncio.to_thread(stand_in.first_done.wait, 5)
        before = text_of(app, "#message")
        await press(pilot, "escape")
        after = text_of(app, "#message")
        stage = app.stage
        stand_in.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert stage is Stage.PLAN
    assert after == before
