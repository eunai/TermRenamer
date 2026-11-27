"""The Applied Stage in full: the counts, then each skipped and each failed file with its
reason. A Sidecar gets a line only when it was not renamed while its video was."""

from __future__ import annotations

import re
from pathlib import Path

from termrenamer.tui.stage import Stage

from .screen_driver import (
    SIZE,
    build,
    make_app,
    press,
    queue,
    screen_text,
    settings,
    text_of,
    tv_backups,
)


def lines_of(app: object, selector: str) -> list[str]:
    """The lines of one Static, each run of spaces one space."""
    text = text_of(app, selector)  # type: ignore[arg-type]
    return [re.sub(r" {2,}", " ", line).strip() for line in text.splitlines()]


async def apply(pilot: object) -> None:
    await press(pilot, "enter", "y")  # type: ignore[arg-type]
    app = pilot.app  # type: ignore[attr-defined]
    await app.workers.wait_for_complete()
    await press(pilot)  # type: ignore[arg-type]


async def test_the_applied_stage_lists_each_skipped_file_with_its_reason(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    for file_name in (
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Harbour Lights - S01E02 - Salt and Rope.mkv",
        "Harbour Lights S01E09.mkv",
        "Quiet Rivers S01E01.mkv",
        "Quiet Rivers S01E01.srt",
        "holiday.mkv",
    ):
        (folder / file_name).write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        assert app.stage is Stage.APPLIED
        counts = lines_of(app, "#applied-counts")
        listed = lines_of(app, "#applied-list")
        heading = lines_of(app, "#applied-heading")
        text = screen_text(app)
    assert counts == ["1 renamed · 3 skipped · 0 failed", "1 already had its name"]
    assert heading == ["Not renamed 3"]
    assert listed == [
        f"Harbour Lights S01E09.mkv {folder}",
        "no match: the episode was not found",
        f"holiday.mkv {folder}",
        "not recognised: its name could not be read",
        f"Quiet Rivers S01E01.mkv {folder}",
        "no match: the show was not found",
    ]
    assert "n New batch" in text


async def test_a_sidecar_not_renamed_while_its_video_was_gets_a_line(tmp_path: Path) -> None:
    folder = tv_backups(tmp_path).resolve()
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        (folder / "Harbour Lights - S01E01 - The Tide Comes In.srt").write_bytes(b"taken")
        await apply(pilot)
        listed = lines_of(app, "#applied-list")
        logs = [line for _n, line in app.log_book.lines_after(0)]
    assert listed[-2:] == [
        f"Harbour Lights S01E01.srt {folder}",
        "Sidecar not renamed: destination exists at apply time",
    ]
    assert any("Harbour Lights S01E01.srt" in line and "skip" in line for line in logs)


async def test_a_renamed_sidecar_gets_no_line_but_is_in_the_logs(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    for file_name in ("Night Ferry S01E01.mkv", "Night Ferry S01E01.srt"):
        (folder / file_name).write_bytes(b"x")
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        await apply(pilot)
        listed = lines_of(app, "#applied-list")
        heading = lines_of(app, "#applied-heading")
        logs = [line for _n, line in app.log_book.lines_after(0)]
    assert heading == ["Not renamed 0"]
    assert listed == ["Every video was renamed."]
    assert any("renamed" in line and "Night Ferry S01E01.srt" in line for line in logs)


async def test_a_failed_file_is_listed_with_its_reason(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    folder = folder.resolve()
    (folder / "Night Ferry S01E01.mkv").write_bytes(b"x")
    root = tmp_path / "TV"
    app = make_app(loaded=settings(folder_rename=True, tv_root=root))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, folder)
        await build(pilot)
        root.write_bytes(b"a file where the Destination root's folder should be")
        await apply(pilot)
        counts = lines_of(app, "#applied-counts")
        listed = lines_of(app, "#applied-list")
    assert counts == ["0 renamed · 0 skipped · 1 failed"]
    assert listed[0] == f"Night Ferry S01E01.mkv {folder}"
    assert listed[1].startswith("failed: mkdir failed:")
