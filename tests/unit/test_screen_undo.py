"""Undo on the screen: `u` on the Applied Stage opens the Undo confirm, `y` puts everything
back and returns to the Queue Stage with the same Sources, `n` or Escape keeps the Apply
(spec #16, sections H and I)."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import ApplyOutcome
from termrenamer.tui.dialogs import UndoConfirm
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages.applied import has_anything_to_undo

from .screen_driver import (
    SIZE,
    build,
    footer_keys,
    make_app,
    names_in,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
)
from .test_screen_applied import apply

FOLDERS = settings(folder_rename=True, season_folders=True)


async def undo(pilot: object) -> None:
    await press(pilot, "u", "y")  # type: ignore[arg-type]
    await pilot.app.workers.wait_for_complete()  # type: ignore[attr-defined]
    await press(pilot)  # type: ignore[arg-type]


async def test_u_opens_the_undo_confirm_and_n_or_escape_keeps_the_apply(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app(loaded=FOLDERS)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        applied = names_in(folder)
        assert "u Undo" in footer_keys(app)
        assert app.screen.query_one("#undo").display

        await press(pilot, "u")
        assert isinstance(app.screen, UndoConfirm)
        lines = text_of(app, "#confirm-lines").splitlines()
        shown = screen_text(app)
        await press(pilot, "n")
        assert not isinstance(app.screen, UndoConfirm)
        await press(pilot, "u", "escape")
        assert not isinstance(app.screen, UndoConfirm)
        assert app.stage is Stage.APPLIED
        message = text_of(app, "#message")
        on_disk = names_in(folder)
    assert "Undo the last Apply?" in shown
    assert "y Put back" in shown
    assert "n Keep" in shown
    assert lines == ["Put 4 files back where they were.", "The Straggler goes back too."]
    assert on_disk == applied
    assert message == "The Apply is kept."


async def test_y_puts_every_file_back_and_returns_to_the_queue(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    before = names_in(folder)
    app = make_app(loaded=FOLDERS)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        assert names_in(folder) != before
        await undo(pilot)
        stage = app.stage
        sources = app.queue.sources
        message = text_of(app, "#message")
        await press(pilot, "u")
        again = app.screen
    assert names_in(folder) == before
    assert stage is Stage.QUEUE
    assert sources == (folder,)
    assert message == "Undo put 5 files back. Nothing was left."
    assert not isinstance(again, UndoConfirm)
    assert app.outcome is None


async def test_a_file_undo_leaves_is_counted_and_in_the_logs_with_its_reason(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app(loaded=FOLDERS)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        changed = folder / "Night Ferry" / "Season 01" / "Night Ferry - S01E01 - Cast Off.mkv"
        changed.write_bytes(b"changed after Apply")
        (folder / "notes.txt").write_bytes(b"new notes")
        await undo(pilot)
        message = text_of(app, "#message")
        logs = [line for _n, line in app.log_book.lines_after(0)]
    assert message == "Undo put 3 files back and left 2: l shows why."
    assert any(str(changed) in line and "changed since Apply" in line for line in logs), logs
    assert any("notes.txt" in line and "its old place is taken" in line for line in logs), logs
    assert changed.read_bytes() == b"changed after Apply"
    assert (folder / "notes.txt").read_bytes() == b"new notes"


async def test_undo_is_not_offered_after_a_new_batch(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app(loaded=FOLDERS)
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        applied = names_in(folder)
        await press(pilot, "n", "u")
        screen = app.screen
        stage = app.stage
    assert app.outcome is None
    assert stage is Stage.QUEUE
    assert not isinstance(screen, UndoConfirm)
    assert names_in(folder) == applied


async def test_undo_is_not_offered_when_apply_moved_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    (folder / "holiday.mkv").write_bytes(b"x")
    (folder / "Quiet Rivers S01E01.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder.resolve())
        await build(pilot)
        await apply(pilot)
        keys = footer_keys(app)
        button = app.screen.query_one("#undo").display
        await press(pilot, "u")
        screen = app.screen
        message = text_of(app, "#message")
    assert "u Undo" not in keys
    assert not button
    assert not isinstance(screen, UndoConfirm)
    assert message == "Apply moved nothing, so there is nothing to undo."


def test_folders_apply_made_alone_offer_no_undo(tmp_path: Path) -> None:
    made = ApplyOutcome(
        results=(), stragglers=(), moves=(), folders_created=(tmp_path,), folders_removed=()
    )
    removed = ApplyOutcome(
        results=(), stragglers=(), moves=(), folders_created=(), folders_removed=(tmp_path,)
    )

    assert not has_anything_to_undo(made)
    assert has_anything_to_undo(removed)
