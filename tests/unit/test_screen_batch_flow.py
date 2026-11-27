"""A batch from the queue to the Applied Stage, driven by keys.

Nothing is renamed before the Apply confirmation: every way to reach Apply is pressed
here, and the files on disk are compared before and after.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest import mock

from termrenamer.core.apply import apply_plan
from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages import PlanStage, PreviewStage
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.title_list import TitleList

from .screen_driver import (
    SIZE,
    build,
    footer_keys,
    make_app,
    names_in,
    press,
    queue,
    screen_text,
    text_of,
    tv_backups,
    tv_stand_in,
    wiring,
)

_BEFORE = [
    "Harbour Lights S01E01.mkv",
    "Harbour Lights S01E01.srt",
    "Harbour Lights S01E02.mkv",
    "Night Ferry S01E01.mkv",
    "holiday.mkv",
    "notes.txt",
]


async def test_the_title_list_fills_while_the_plan_is_built(tmp_path: Path) -> None:
    stand_in = tv_stand_in(hold=True)
    app = make_app(wiring(tv=stand_in))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await press(pilot, "b")
        assert await asyncio.to_thread(stand_in.first_done.wait, 5)
        await pilot.pause()
        during = screen_text(app)
        rows = [
            (row.name, row.status) for row in app.query_one(PlanStage).query_one(TitleList).rows
        ]
        stage_during = app.stage
        keys_during = footer_keys(app)
        stand_in.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stage is Stage.PREVIEW
    assert stage_during is Stage.PLAN
    assert rows == [
        ("Harbour Lights", "found"),
        ("Night Ferry", "looking up"),
        ("holiday.mkv", "not recognised"),
    ]
    assert "Building the Plan…" in during
    assert "on TMDB…" in during
    assert "✓ Queue" in during and "● Plan" in during
    assert "b Build Plan" not in keys_during
    assert not any(key.startswith(("a ", "f ", "c ")) for key in keys_during)


async def test_the_preview_has_one_row_per_title_and_one_per_not_recognised_video(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        text = screen_text(app)
        rows = [
            (r.name, r.status, r.count)
            for r in app.query_one(PreviewStage).query_one(TitleList).rows
        ]
    assert rows == [
        ("Harbour Lights", "ready", "2"),
        ("Night Ferry", "ready", "1"),
        ("holiday.mkv", "not recognised", "1"),
    ]
    assert "✓ Queue" in text and "✓ Plan" in text and "● Preview" in text
    assert "2 Titles · 4 videos" in text
    assert "Titles 3" in text  # the heading counts every row of the list, as the mockup does
    assert "enter Apply…" in text
    assert "Nothing moves until you confirm." in text


async def test_up_and_down_select_a_title_at_the_preview(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        preview = app.query_one(PreviewStage)
        first = preview.selected_row
        await press(pilot, "down")
        second = preview.selected_row
        await press(pilot, "down", "down", "down")
        last = preview.selected_row
        await press(pilot, "up")
        back = preview.selected_row
    assert first is not None and first.name == "Harbour Lights"
    assert second is not None and second.name == "Night Ferry"
    assert last is not None and last.name == "holiday.mkv"
    assert back is not None and back.name == "Night Ferry"


async def test_escape_at_the_preview_discards_the_plan_and_keeps_the_queue(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "escape")
        text = screen_text(app)
        assert app.stage is Stage.QUEUE
        assert app.plan is None
        assert app.queue.sources == (folder.resolve(),)
    assert "Plan discarded. Nothing was renamed." in text
    assert names_in(folder) == _BEFORE


async def test_enter_opens_the_apply_confirm_and_n_or_escape_renames_nothing(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        for answer in ("n", "escape"):
            await press(pilot, "enter")
            assert isinstance(app.screen, ApplyConfirm)
            text = screen_text(app)
            assert names_in(folder) == _BEFORE
            await press(pilot, answer)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not isinstance(app.screen, ApplyConfirm)
            assert app.stage is Stage.PREVIEW
            assert names_in(folder) == _BEFORE
    assert "Apply the Plan?" in text
    assert "Rename 3 videos in their own folders." in text
    assert "Skip 1 video: 1 not recognised" in text
    assert "Nothing has been renamed yet." in text


async def test_clicking_apply_opens_the_confirm_and_renames_nothing(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        button = app.query_one(PreviewStage).query_one(ActionButton)
        await pilot.click(button)
        await pilot.pause()
        assert isinstance(app.screen, ApplyConfirm)
        assert names_in(folder) == _BEFORE
        await press(pilot, "n")
    assert names_in(folder) == _BEFORE


async def test_no_other_key_at_the_preview_renames_anything(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        for key in ("y", "space", "b", "t", "x", "u", "left", "right", "i"):
            await press(pilot, key)
            await app.workers.wait_for_complete()
            assert app.stage is Stage.PREVIEW
            assert app.screen is app.screen_stack[0]
            assert names_in(folder) == _BEFORE


async def test_y_or_enter_in_the_confirm_applies_and_shows_the_counts(tmp_path: Path) -> None:
    for answer in ("y", "enter"):
        folder = tv_backups(tmp_path, f"Backups {answer}")
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await queue(pilot, folder)
            await build(pilot)
            await press(pilot, "enter", answer)
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = screen_text(app)
            assert app.stage is Stage.APPLIED
        assert names_in(folder) == [
            "Harbour Lights - S01E01 - The Tide Comes In.mkv",
            "Harbour Lights - S01E01 - The Tide Comes In.srt",
            "Harbour Lights - S01E02 - Salt and Rope.mkv",
            "Night Ferry - S01E01 - Cast Off.mkv",
            "holiday.mkv",
            "notes.txt",
        ]
        assert "3 renamed · 1 skipped · 0 failed" in text
        assert "✓ Preview" in text and "● Applied" in text


async def test_n_at_the_applied_stage_starts_a_new_batch_with_an_empty_queue(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "n New batch" in footer_keys(app)
        await press(pilot, "n")
        text = screen_text(app)
        assert app.stage is Stage.QUEUE
        assert app.queue.sources == ()
        assert app.outcome is None
    assert "Nothing queued yet" in text
    assert "● Queue" in text


async def test_a_build_that_fails_returns_to_the_queue_with_its_message(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app(wiring(tmdb=False))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        text = screen_text(app)
        assert app.stage is Stage.QUEUE
        assert app.plan is None
        assert not app.session_settings.locked
    assert "TMDB requires an API key" in text
    assert names_in(folder) == _BEFORE


async def test_a_queue_with_no_video_builds_no_plan(tmp_path: Path) -> None:
    folder = tmp_path / "Notes"
    folder.mkdir()
    (folder / "readme.txt").write_text("x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        text = screen_text(app)
        assert app.stage is Stage.QUEUE
    assert "No video was found in the queued Sources." in text


async def test_an_apply_that_raises_shows_its_message_and_unlocks(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        with mock.patch("termrenamer.tui.app.apply_plan", side_effect=RuntimeError("disk gone")):
            await press(pilot, "enter", "y")
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert "Apply failed: disk gone" in text_of(app, "#message")
        assert not app.session_settings.locked
    assert names_in(folder) == _BEFORE


async def test_settings_mode_and_provider_are_refused_while_the_plan_is_applied(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    go = threading.Event()

    def slow_apply(plan, *, confirmed):  # type: ignore[no-untyped-def]
        started.set()
        go.wait(timeout=10)
        return apply_plan(plan, confirmed=confirmed)

    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        with mock.patch("termrenamer.tui.app.apply_plan", side_effect=slow_apply):
            await press(pilot, "enter", "y")
            assert await asyncio.to_thread(started.wait, 5)
            messages = []
            for key in ("s", "m", "p", "escape"):
                await press(pilot, key)
                messages.append(text_of(app, "#message"))
            stage_during = app.stage
            go.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert app.stage is Stage.APPLIED
    assert stage_during is Stage.PREVIEW
    assert messages[:3] == [
        "Settings cannot change while a Plan is being built or applied.",
        "Mode cannot change while a Plan is being built or applied.",
        "Provider cannot change while a Plan is being built or applied.",
    ]


async def test_after_apply_a_settings_change_discards_nothing(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await press(pilot, "s", "down", "down", "enter", "escape")
        assert app.stage is Stage.APPLIED
        assert "Plan discarded" not in text_of(app, "#message")


async def test_the_confirm_does_not_count_a_video_that_already_has_its_name(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    (folder / "Harbour Lights - S01E01 - The Tide Comes In.mkv").write_bytes(b"x")
    (folder / "Harbour Lights S01E02.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        text = screen_text(app)
        await press(pilot, "n")
    assert "Rename 1 video in its own folder." in text
