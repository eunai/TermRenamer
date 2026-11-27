"""Name taken on the screen: the Preview, its footer, the Apply confirm and the Applied Stage."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.policies import NameTakenPolicy
from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.stage import Stage

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
)

TAKEN_VIDEO = "Night Ferry - S01E01 - Cast Off.mkv"
TAKEN_SUBTITLE = "Harbour Lights - S01E01 - The Tide Comes In.srt"


def backups_with_taken_names(parent: Path) -> Path:
    """Night Ferry's new name is taken by a folder; Harbour Lights E01's subtitle's by a file."""
    folder = parent / "TV Backups"
    folder.mkdir()
    for name in (
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Harbour Lights S01E02.mkv",
        "Night Ferry S01E01.mkv",
    ):
        (folder / name).write_bytes(b"x")
    (folder / TAKEN_SUBTITLE).write_bytes(b"old subtitle")
    (folder / TAKEN_VIDEO).mkdir()
    return folder


async def test_under_suffix_the_footer_says_the_file_gets_a_number(tmp_path: Path) -> None:
    folder = backups_with_taken_names(tmp_path)
    app = make_app(loaded=settings(name_taken=NameTakenPolicy.SUFFIX))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "down")
        text = screen_text(app)

    assert lines_with(text, "Night Ferry")[0].endswith("name taken 1")
    assert "Name taken: it gets a number, as Night Ferry - S01E01 - Cast Off (1).mkv." in text


async def test_under_skip_the_footer_says_apply_skips_the_file(tmp_path: Path) -> None:
    folder = backups_with_taken_names(tmp_path)
    app = make_app(loaded=settings(name_taken=NameTakenPolicy.SKIP))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "down")
        text = screen_text(app)

    assert lines_with(text, "Night Ferry")[0].endswith("name taken 1")
    assert "Name taken: Apply skips it, and it stays where it is." in text


async def test_under_skip_the_confirm_and_the_applied_stage_list_the_skipped_files(
    tmp_path: Path,
) -> None:
    folder = backups_with_taken_names(tmp_path)
    app = make_app(loaded=settings(name_taken=NameTakenPolicy.SKIP))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        assert isinstance(app.screen, ApplyConfirm)
        confirm = screen_text(app)
        assert names_in(folder) == sorted(
            [
                "Harbour Lights S01E01.mkv",
                "Harbour Lights S01E01.srt",
                "Harbour Lights S01E02.mkv",
                "Night Ferry S01E01.mkv",
                TAKEN_SUBTITLE,
                TAKEN_VIDEO,
            ]
        )
        await press(pilot, "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stage is Stage.APPLIED
        applied = screen_text(app)

    assert "Rename 2 videos in their own folders." in confirm
    assert "Skip 0 with no match · 0 not recognised · 1 name taken" in confirm
    assert "Sidecar skipped: Harbour Lights S01E01.srt · name taken" in confirm
    assert "2 renamed · 1 skipped · 0 failed" in applied
    assert "Night Ferry S01E01.mkv · name taken" in applied
    assert "Sidecar skipped: Harbour Lights S01E01.srt · name taken" in applied
    assert names_in(folder) == sorted(
        [
            "Harbour Lights - S01E01 - The Tide Comes In.mkv",
            "Harbour Lights - S01E02 - Salt and Rope.mkv",
            "Harbour Lights S01E01.srt",
            "Night Ferry S01E01.mkv",
            TAKEN_SUBTITLE,
            TAKEN_VIDEO,
        ]
    )
    assert (folder / TAKEN_SUBTITLE).read_bytes() == b"old subtitle"


async def test_under_suffix_every_file_is_renamed_with_its_number(tmp_path: Path) -> None:
    folder = backups_with_taken_names(tmp_path)
    app = make_app(loaded=settings(name_taken=NameTakenPolicy.SUFFIX))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "enter")
        confirm = screen_text(app)
        await press(pilot, "y")
        await app.workers.wait_for_complete()
        await pilot.pause()
        applied = screen_text(app)

    assert "Rename 3 videos in their own folders." in confirm
    assert "Sidecar skipped" not in confirm
    assert "3 renamed · 0 skipped · 0 failed" in applied
    assert names_in(folder) == sorted(
        [
            "Harbour Lights - S01E01 - The Tide Comes In.mkv",
            "Harbour Lights - S01E01 - The Tide Comes In (1).srt",
            "Harbour Lights - S01E02 - Salt and Rope.mkv",
            "Night Ferry - S01E01 - Cast Off (1).mkv",
            TAKEN_SUBTITLE,
            TAKEN_VIDEO,
        ]
    )
