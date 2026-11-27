"""Leave out on the Preview: ``x`` leaves the selected video out of the Plan and puts it back.

Driven by keys, read off the screen and the disk.
"""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from termrenamer.core.models import EntryStatus
from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.stage import Stage

from .links import point_folder_at
from .screen_driver import (
    SIZE,
    build,
    lines_with,
    make_app,
    names_in,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
)

WIDE = (300, 40)
"""Wide enough that the footer shows each path whole."""


def has_row(text: str, name: str, status_and_count: str) -> bool:
    """Whether the Title list's row for ``name`` ends in ``status_and_count``; the details
    column also names the selected Title."""
    return any(line.endswith(status_and_count) for line in lines_with(text, name))


async def test_x_leaves_the_selected_video_out_and_keeps_the_selection(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "right", "x")
        text = screen_text(app)
        footer = text_of(app, "#stage-lines").splitlines()
        heading = text_of(app, "#details-heading").splitlines()
        tally = text_of(app, "#details-tally")
        summary = text_of(app, "#summary-counts")
        button = text_of(app, "#leave-out")
        marks = text_of(app, "#details-cells").splitlines()[2]

    assert "Left out of the Plan: Apply does not touch this file." in text
    # Still the Title and the file that were selected.
    assert heading[0] == "Harbour Lights"
    assert footer[0].split(maxsplit=1) == ["from", str(folder / "Harbour Lights S01E02.mkv")]
    assert footer[1].split(maxsplit=1) == [
        "to",
        f"{folder / 'Harbour Lights - S01E02 - Salt and Rope.mkv'}"
        " · left out, so Apply does not touch it",
    ]
    assert marks.split() == ["▔▔"] and marks.index("▔▔") > 6
    # The Title is not left out while one of its files is still in the Plan.
    assert has_row(text, "Harbour Lights", "ready 2")
    assert tally.split(" · ") == ["1 ready", "1 left out"]
    assert summary.splitlines()[2] == "1 left out"
    assert button.strip() == "x  Put back"


async def test_x_again_puts_the_video_back_as_a_fresh_plan_has_it(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        built = app.plan
        await press(pilot, "right", "x", "x")
        text = screen_text(app)
        footer = text_of(app, "#stage-lines").splitlines()
        summary = text_of(app, "#summary-counts")
        button = text_of(app, "#leave-out")

    assert "Put back in the Plan." in text
    assert app.plan == built
    assert footer[1].split(maxsplit=1) == [
        "to",
        str(folder / "Harbour Lights - S01E02 - Salt and Rope.mkv"),
    ]
    assert summary.splitlines()[2] == "0 left out"
    assert button.strip() == "x  Leave out"


async def test_a_title_whose_every_file_is_left_out_says_left_out(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "down", "x")
        text = screen_text(app)
        heading = text_of(app, "#details-heading").splitlines()

    assert has_row(text, "Night Ferry", "left out 1")
    assert heading == ["Night Ferry", "left out · 1 season · 1 video"]


async def test_x_on_a_not_recognised_file_says_so_and_changes_nothing(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        built = app.plan
        await press(pilot, "down", "down", "x")
        text = screen_text(app)

    assert app.plan is built
    assert (
        "Nothing to leave out: Apply does not rename a file with the status not recognised." in text
    )


async def test_x_on_a_file_with_no_match_says_so_and_changes_nothing(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path)
    (folder / "Lost Signal S01E01.mkv").write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        built = app.plan
        # Harbour Lights, Lost Signal, Night Ferry, holiday.mkv
        await press(pilot, "down", "x")
        text = screen_text(app)

    assert app.plan is built
    assert "Nothing to leave out: Apply does not rename a file with the status no match." in text


async def test_apply_leaves_the_left_out_video_and_its_sidecar_and_counts_it_as_left_out(
    tmp_path: Path,
) -> None:
    folder = tv_backups(tmp_path)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        # The first episode of Harbour Lights, with its subtitle.
        await press(pilot, "x", "enter")
        assert isinstance(app.screen, ApplyConfirm)
        confirm = screen_text(app)
        await press(pilot, "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stage is Stage.APPLIED
        applied = screen_text(app)
        counts = text_of(app, "#applied-counts")

    assert "Rename 2 videos in their own folders." in confirm
    assert "Skip 1 video: 1 not recognised" in confirm
    assert "Leave out 1 video: Apply does not touch it." in confirm
    assert names_in(folder) == [
        "Harbour Lights - S01E02 - Salt and Rope.mkv",
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Night Ferry - S01E01 - Cast Off.mkv",
        "holiday.mkv",
        "notes.txt",
    ]
    assert counts.splitlines()[0] == "2 renamed · 1 skipped · 0 failed"
    assert "1 left out" in counts.splitlines()[1:]
    assert lines_with(applied, "Harbour Lights S01E01.mkv")
    assert "left out" in applied


async def test_at_90_by_28_the_arrows_still_select_when_the_details_scroll(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=(90, 28)) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        # A mixed Title adds its tally line, so the details column needs to scroll.
        await press(pilot, "x", "right")
        second_file = text_of(app, "#stage-lines").splitlines()[0]
        await press(pilot, "down")
        heading = text_of(app, "#details-heading").splitlines()

    assert second_file.endswith("Harbour Lights S01E02.mkv")
    assert heading[0] == "Night Ferry"


async def test_at_90_by_28_the_put_back_button_stays_on_screen_and_works(tmp_path: Path) -> None:
    app = make_app()
    async with app.run_test(size=(90, 28)) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "x")
        built_status = app.plan.videos[0].status if app.plan else None
        await pilot.click("#leave-out")
        await pilot.pause()
        text = screen_text(app)

    assert built_status is EntryStatus.LEFT_OUT
    assert "Put back in the Plan." in text
    assert app.plan is not None and app.plan.videos[0].status is EntryStatus.READY


async def test_the_footer_strikes_the_name_the_file_would_get_if_put_back(tmp_path: Path) -> None:
    folder = (tmp_path / "Film Backups").resolve()
    folder.mkdir()
    # The file already at the name sorts first, so the other gets the number.
    (folder / "Metropolis (1927).mkv").write_bytes(b"x")
    (folder / "Metropolis 1927.mkv").write_bytes(b"y")
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "right")
        before = text_of(app, "#stage-lines").splitlines()[1]
        await press(pilot, "x")
        after = text_of(app, "#stage-lines").splitlines()[1]

    numbered = str(folder / "Metropolis (1927) (1).mkv")
    assert before.split(maxsplit=1)[1].startswith(numbered)
    assert after.split(maxsplit=1) == ["to", f"{numbered} · left out, so Apply does not touch it"]


@contextmanager
def _cannot_be_entered(folder: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``folder`` cannot be entered: by POSIX permissions where they bind; on Windows, or
    for root, by a permission error from every look at a name inside it."""
    if sys.platform != "win32" and os.geteuid() != 0:
        folder.chmod(0)
        try:
            yield
        finally:
            folder.chmod(0o755)
        return
    real_stat = Path.stat

    def stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if folder in self.parents:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real_stat(self, follow_symlinks=follow_symlinks)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "stat", stat)
        yield


async def test_x_keeps_the_plan_when_the_disk_cannot_be_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Library"
    library.mkdir()
    app = make_app(loaded=settings(folder_rename=True, tv_root=library))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        built = app.plan
        with _cannot_be_entered(library, monkeypatch):
            await press(pilot, "x")
            text = screen_text(app)

    assert app.plan is built
    assert "The new names could not be checked on disk:" in text


async def test_x_twice_puts_back_the_same_file_after_its_folder_is_redirected(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "TV"
    for disc in ("Disc A", "Disc B"):
        (folder / disc).mkdir(parents=True)
        (folder / disc / "Night Ferry S01E01.mkv").write_bytes(disc.encode())
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        built = app.plan
        # Night Ferry's second file is Disc B's; then Disc B points to a copy that sorts first.
        await press(pilot, "down", "right")
        copy = tmp_path / "Aaa"
        copy.mkdir()
        (copy / "Night Ferry S01E01.mkv").write_bytes(b"Disc B")
        (folder / "Disc B").rename(tmp_path / "Disc B moved")
        point_folder_at(folder / "Disc B", copy)
        await press(pilot, "x")
        left_out = [v.source.parent.name for v in app.plan.videos if v.status.value == "left out"]
        await press(pilot, "x")

    assert left_out == ["Disc B"]
    assert app.plan == built
