"""How the screen writes a folder: its path and one separator of its own system."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from termrenamer.tui.words import folder_text


def test_a_windows_folder_ends_with_one_backslash() -> None:
    assert folder_text(PureWindowsPath("D:/media/Shows")) == "D:\\media\\Shows\\"


def test_a_posix_folder_ends_with_one_slash() -> None:
    assert folder_text(PurePosixPath("/media/Shows")) == "/media/Shows/"


def test_a_root_folder_keeps_its_one_separator() -> None:
    assert folder_text(PureWindowsPath("D:/")) == "D:\\"
    assert folder_text(PurePosixPath("/")) == "/"
