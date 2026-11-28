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


def test_season_folder_loaded_on_while_folder_rename_is_off_starts_off() -> None:
    from termrenamer.app_bootstrap import Settings

    loaded = Settings(
        tmdb_api_key=None,
        tvdb_api_key=None,
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=1.0,
        http_max_attempts=1,
        http_backoff_base_seconds=0.0,
        http_jitter=False,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=None,
        enable_folder_rename=False,
        enable_season_folders=True,
    )
    owner = SessionSettings(loaded)
    assert owner.season_folders is False
    owner.set_folder_rename(True)
    assert owner.plan_options().season_folders is False


def test_name_taken_starts_as_loaded_and_goes_into_the_plan_options() -> None:
    from termrenamer.core.policies import NameTakenPolicy

    from .screen_driver import settings

    assert SessionSettings(None).plan_options().name_taken is NameTakenPolicy.SUFFIX
    owner = SessionSettings(settings(name_taken=NameTakenPolicy.SKIP))
    assert owner.name_taken is NameTakenPolicy.SKIP
    assert owner.plan_options().name_taken is NameTakenPolicy.SKIP


def test_a_name_taken_change_is_reported_and_refused_while_locked() -> None:
    from termrenamer.core.policies import NameTakenPolicy

    owner = SessionSettings(None)
    heard: list[str] = []
    owner.add_listener(heard.append)

    assert owner.set_name_taken(NameTakenPolicy.SUFFIX) is False
    assert owner.set_name_taken(NameTakenPolicy.SKIP) is True
    assert heard == ["Name taken"]
    assert owner.plan_options().name_taken is NameTakenPolicy.SKIP

    owner.lock()
    with pytest.raises(SettingsLockedError):
        owner.set_name_taken(NameTakenPolicy.SUFFIX)
    assert owner.name_taken is NameTakenPolicy.SKIP
    assert heard == ["Name taken"]
