"""The Preview summary and the Apply confirm count the Stragglers to merge; the Applied
Stage counts the Stragglers merged."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.stage import Stage
from termrenamer.tui.words import folder_text

from .screen_driver import SIZE, build, make_app, press, queue, settings
from .test_screen_applied import apply, lines_of


def _two_discs(parent: Path) -> Path:
    """Harbour Lights on two discs, each with a ``folder.jpg``; disc 1 also has a note."""
    folder = parent / "TV Backups"
    for path, data in (
        ("Disc 1/Harbour Lights S01E01.mkv", b"v"),
        ("Disc 1/folder.jpg", b"j1"),
        ("Disc 1/notes.txt", b"n"),
        ("Disc 2/Harbour Lights S01E02.mkv", b"v"),
        ("Disc 2/folder.jpg", b"j2"),
    ):
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)
    return folder.resolve()


async def test_the_preview_the_confirm_and_the_applied_stage_count_the_stragglers(
    tmp_path: Path,
) -> None:
    folder = _two_discs(tmp_path)
    app = make_app(loaded=settings(folder_rename=True, season_folders=True))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        summary = lines_of(app, "#summary-counts")
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        confirm = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
        await apply(pilot)
        assert app.stage is Stage.APPLIED
        counts = lines_of(app, "#applied-counts")
    assert summary[-1] == "0 left out · 3 Stragglers merge"
    assert confirm[:3] == [
        "Rename 2 videos in their own folders.",
        "Skip none.",
        "Merge 3 Stragglers (Harbour Lights)",
    ]
    assert counts == ["2 renamed · 0 skipped · 0 failed", "3 Stragglers merged"]
    season = folder / "Harbour Lights" / "Season 01"
    assert set(folder.rglob("*")) == {
        folder / "Harbour Lights",
        season,
        season / "Harbour Lights - S01E01 - The Tide Comes In.mkv",
        season / "Harbour Lights - S01E02 - Salt and Rope.mkv",
        season / "folder (1).jpg",
        season / "folder.jpg",
        season / "notes.txt",
    }


async def test_with_folder_rename_on_and_nothing_left_behind_the_confirm_says_so(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "TV Backups"
    (folder / "Disc 1").mkdir(parents=True)
    (folder / "Disc 1" / "Harbour Lights S01E01.mkv").write_bytes(b"v")
    app = make_app(loaded=settings(folder_rename=True, season_folders=True))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder.resolve())
        await build(pilot)
        summary = lines_of(app, "#summary-counts")
        await press(pilot, "enter")
        confirm = lines_of(app, "#confirm-lines")
        await press(pilot, "n")
        await apply(pilot)
        counts = lines_of(app, "#applied-counts")
    assert summary[-1] == "0 left out"
    assert confirm[2] == "No Stragglers in this Plan."
    assert counts == ["1 renamed · 0 skipped · 0 failed"]


async def test_a_straggler_not_merged_is_listed_with_its_reason_and_a_failure_counts(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "TV Backups"
    mixed = folder / "Mixed"
    mixed.mkdir(parents=True)
    for name in ("Harbour Lights S01E01.mkv", "Night Ferry S01E01.mkv", "folder.jpg"):
        (mixed / name).write_bytes(b"x")
    folder = folder.resolve()
    mixed = folder / "Mixed"
    app = make_app(loaded=settings(folder_rename=True, season_folders=True))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        # The Straggler's target folder is Harbour Lights's; that video changes and is
        # skipped, and a file now stands where its folder would be made.
        (mixed / "Harbour Lights S01E01.mkv").write_bytes(b"changed since planning")
        (folder / "Harbour Lights").write_bytes(b"in the way")
        await apply(pilot)
        counts = lines_of(app, "#applied-counts")
        title = lines_of(app, "#applied-title")
        listed = lines_of(app, "#applied-list")
        message = lines_of(app, "#message")
    assert counts == ["1 renamed · 1 skipped · 0 failed", "0 Stragglers merged · 1 not merged"]
    assert title == ["The Plan is applied."]
    assert message == ["Applied."]
    assert listed[-2] == f"folder.jpg {folder_text(mixed)}"
    assert listed[-1].startswith("Straggler not merged: failed: ")
    assert (mixed / "folder.jpg").read_bytes() == b"x"


async def test_the_file_dialog_opens_in_the_home_folder_when_the_working_folder_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer.tui import app as app_module
    from termrenamer.tui.dialogs import FilePicker, FolderPicker

    def gone() -> Path:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(app_module.Path, "cwd", staticmethod(gone))
    monkeypatch.setattr(app_module.Path, "home", staticmethod(lambda: tmp_path))
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "a")
        file_dialog = app.screen
        await press(pilot, "escape")
        await press(pilot, "f")
        folder_dialog = app.screen
    assert isinstance(file_dialog, FilePicker)
    assert isinstance(folder_dialog, FolderPicker)
