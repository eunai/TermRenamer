"""The session's settings owner: the plan options it gives and its lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.core.models import ScanMode
from termrenamer.session_settings import SessionSettings, SettingsLockedError


def test_while_locked_every_setting_is_refused_and_left_as_it_was(tmp_path: Path) -> None:
    owner = SessionSettings(None)
    heard: list[str] = []
    owner.add_listener(heard.append)
    owner.lock()

    changes = [
        lambda: owner.set_mode(ScanMode.FILM),
        lambda: owner.set_provider("tvdb"),
        lambda: owner.set_destination_root(ScanMode.TV, tmp_path),
        lambda: owner.set_folder_rename(True),
        lambda: owner.set_season_folders(True),
    ]
    for change in changes:
        with pytest.raises(SettingsLockedError, match="cannot change while a Plan"):
            change()

    assert (owner.mode, owner.provider_id) == (ScanMode.TV, "tmdb")
    assert owner.destination_root(ScanMode.TV) is None
    assert (owner.folder_rename, owner.season_folders) == (False, False)
    assert heard == []
    owner.unlock()
    assert owner.set_mode(ScanMode.FILM) is True
    assert heard == ["Mode"]
