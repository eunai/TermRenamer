"""The footer's key hints: the keys that work right now, as many as fit, by one rule.

When the hints are wider than the footer, they are dropped in this order until the rest
fit: Poster, Logs, Provider, Mode, Settings, Quit, then the selection keys, then the
Stage's own keys from the last. Help is never dropped: it lists every key. While an
Apply, an Undo or a build runs, a key whose action refuses is not listed.

Driven by keys, read off the screen's last row.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from termrenamer.tui import app as screen
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.stage import Stage

from .screen_driver import (
    build,
    make_app,
    press,
    queue,
    screen_lines,
    tv_backups,
    tv_stand_in,
    wiring,
)

PREVIEW_HINTS = {
    120: [
        "↑↓ Select",
        "←→ File",
        "enter Apply…",
        "t Match",
        "x Leave out",
        "m Mode",
        "esc Discard Plan",
        "s Settings",
        "? Help",
        "q Quit",
    ],
    100: [
        "↑↓ Select",
        "←→ File",
        "enter Apply…",
        "t Match",
        "x Leave out",
        "esc Discard Plan",
        "? Help",
        "q Quit",
    ],
    90: [
        "↑↓ Select",
        "←→ File",
        "enter Apply…",
        "t Match",
        "x Leave out",
        "esc Discard Plan",
        "? Help",
        "q Quit",
    ],
}
"""The Preview's hints at each width, worked out by hand from the rule: all thirteen
take 138 cells; the footer gives its width less 2."""

WIDE_PREVIEW = [
    "↑↓ Select",
    "←→ File",
    "enter Apply…",
    "t Match",
    "x Leave out",
    "i Poster",
    "m Mode",
    "p Provider",
    "esc Discard Plan",
    "s Settings",
    "l Logs",
    "? Help",
    "q Quit",
]


def hints(app: TermRenamerApp) -> str:
    """The footer's last row as drawn, columns kept."""
    return screen_lines(app)[-1]


def shown(app: TermRenamerApp, candidates: list[str]) -> list[str]:
    row = hints(app)
    return [hint for hint in candidates if f" {hint} " in f" {row} "]


@pytest.mark.parametrize("width", [90, 100, 120])
async def test_the_preview_footer_drops_hints_by_the_rule_and_keeps_help(
    tmp_path: Path, width: int
) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=(width, 36)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        row = hints(app)
        listed = shown(app, WIDE_PREVIEW)

    assert listed == PREVIEW_HINTS[width]
    # Each hint shown is whole: nothing is cut at the right edge.
    assert row.rstrip().endswith(PREVIEW_HINTS[width][-1])


async def test_a_footer_wide_enough_lists_every_working_key(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=(160, 36)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        listed = shown(app, WIDE_PREVIEW)
    assert listed == WIDE_PREVIEW


@pytest.mark.parametrize("width", [90, 100, 120])
async def test_help_is_listed_at_every_stage_and_width(tmp_path: Path, width: int) -> None:
    folder = tv_backups(tmp_path).resolve()
    tv = tv_stand_in(hold=True)
    app = make_app(wiring(tv=tv))
    rows = {}
    async with app.run_test(size=(width, 36)) as pilot:
        rows[Stage.QUEUE] = hints(app)
        await queue(pilot, folder)
        await press(pilot, "b")
        assert tv.first_done.wait(timeout=5)
        await pilot.pause()
        rows[Stage.PLAN] = hints(app)
        tv.go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        rows[Stage.PREVIEW] = hints(app)
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        rows[Stage.APPLIED] = hints(app)

    for stage, row in rows.items():
        assert "? Help" in row, (stage, row)
    assert "esc Cancel Plan" in rows[Stage.PLAN]
    assert "n New batch" in rows[Stage.APPLIED]


async def test_while_apply_runs_the_footer_lists_no_key_that_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tv_backups(tmp_path).resolve()
    go, started = threading.Event(), threading.Event()
    applying = screen.apply_plan

    def held(*args: object, **kwargs: object) -> object:
        started.set()
        assert go.wait(timeout=10)
        return applying(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(screen, "apply_plan", held)
    app = make_app()
    async with app.run_test(size=(160, 36)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter", "y")
        assert started.wait(timeout=5)
        await pilot.pause()
        during = hints(app)
        go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

    for refused in (
        "Apply…",
        "t Match",
        "x Leave out",
        "Discard Plan",
        "Mode",
        "Provider",
        "Settings",
    ):
        assert refused not in during, (refused, during)
    assert "? Help" in during and "↑↓ Select" in during


async def test_while_undo_runs_the_footer_lists_no_key_that_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tv_backups(tmp_path).resolve()
    go, started = threading.Event(), threading.Event()
    undoing = screen.undo_apply

    def held(*args: object, **kwargs: object) -> object:
        started.set()
        assert go.wait(timeout=10)
        return undoing(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(screen, "undo_apply", held)
    app = make_app()
    async with app.run_test(size=(160, 36)) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter", "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        before = hints(app)
        await press(pilot, "u", "y")
        assert started.wait(timeout=5)
        await pilot.pause()
        during = hints(app)
        go.set()
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert "n New batch" in before and "s Settings" in before
    for refused in ("u Undo", "n New batch", "s Settings"):
        assert refused not in during, (refused, during)
    assert "? Help" in during
