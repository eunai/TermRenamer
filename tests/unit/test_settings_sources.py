"""Where settings come from: environment, the current folder's `.env`, the user settings file."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.app_bootstrap import load_settings
from termrenamer.util.errors import ValidationError
from termrenamer.wiring import PlanningWiring

if TYPE_CHECKING:
    from conftest import IsolatedDirs


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("platform", "folder"),
    [("win32", "appdata"), ("linux", "config_home"), ("darwin", "config_home")],
)
def test_fixture_user_settings_file_follows_the_running_platform(
    platform: str,
    folder: str,
    isolated_settings_dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared fixture puts the user settings file where the app reads it on each platform."""
    monkeypatch.setattr(sys, "platform", platform)
    base: Path = getattr(isolated_settings_dirs, folder)

    assert isolated_settings_dirs.user_settings_file == base / "termrenamer" / ".env"


def test_user_settings_file_alone_supplies_a_value(isolated_settings_dirs: IsolatedDirs) -> None:
    _write(isolated_settings_dirs.user_settings_file, "TERMRENAMER_TMDB_API_KEY=from-user-file\n")

    settings = load_settings()

    assert settings.tmdb_api_key == "from-user-file"


def test_current_folder_env_alone_supplies_a_value(isolated_settings_dirs: IsolatedDirs) -> None:
    _write(isolated_settings_dirs.workdir / ".env", "TERMRENAMER_TMDB_API_KEY=from-folder\n")

    settings = load_settings()

    assert settings.tmdb_api_key == "from-folder"


def _set_source(
    source: str, text_value: str, dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = f"TERMRENAMER_TMDB_API_KEY={text_value}\n"
    if source == "environment":
        monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", text_value)
    elif source == "folder":
        _write(dirs.workdir / ".env", line)
    else:
        _write(dirs.user_settings_file, line)


@pytest.mark.parametrize(
    ("higher", "lower"),
    [("environment", "folder"), ("environment", "user"), ("folder", "user")],
)
def test_higher_source_wins_over_lower(
    higher: str,
    lower: str,
    isolated_settings_dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_source(lower, "lower-value", isolated_settings_dirs, monkeypatch)
    _set_source(higher, "higher-value", isolated_settings_dirs, monkeypatch)

    settings = load_settings()

    assert settings.tmdb_api_key == "higher-value"


def test_every_source_contributes_its_own_variables(
    isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "env-key")
    _write(
        isolated_settings_dirs.workdir / ".env",
        "TERMRENAMER_TMDB_API_KEY=folder-key\nTERMRENAMER_ENABLE_FOLDER_RENAME=true\n",
    )
    _write(
        isolated_settings_dirs.user_settings_file,
        "TERMRENAMER_TMDB_API_KEY=user-key\n"
        "TERMRENAMER_ENABLE_FOLDER_RENAME=false\n"
        "TERMRENAMER_OMDB_API_KEY=user-omdb\n",
    )

    settings = load_settings()

    assert settings.tmdb_api_key == "env-key"
    assert settings.enable_folder_rename is True
    assert settings.omdb_api_key == "user-omdb"


@pytest.mark.parametrize("higher", ["environment", "folder"])
def test_blank_value_in_higher_source_leaves_lower_value(
    higher: str, isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank line, as in a copy of `.env.example`, means "not set" in every source."""
    _set_source("user", "user-key", isolated_settings_dirs, monkeypatch)
    _set_source(higher, "  ", isolated_settings_dirs, monkeypatch)

    settings = load_settings()

    assert settings.tmdb_api_key == "user-key"


def test_env_in_a_parent_of_the_working_folder_is_ignored(
    isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = isolated_settings_dirs.workdir / "Show" / "Season 01"
    child.mkdir(parents=True)
    _write(isolated_settings_dirs.workdir / ".env", "TERMRENAMER_TMDB_API_KEY=from-parent\n")
    monkeypatch.chdir(child)
    monkeypatch.setenv("TERMRENAMER_OMDB_API_KEY", "made-up-omdb")

    settings = load_settings()

    assert settings.tmdb_api_key is None


def test_explicit_file_is_the_only_file_read(
    isolated_settings_dirs: IsolatedDirs, tmp_path: Path
) -> None:
    _write(
        isolated_settings_dirs.user_settings_file,
        "TERMRENAMER_TMDB_API_KEY=user-key\nTERMRENAMER_OMDB_API_KEY=user-omdb\n",
    )
    _write(isolated_settings_dirs.workdir / ".env", "TERMRENAMER_TVDB_API_KEY=folder-tvdb\n")
    explicit = _write(tmp_path / "explicit.env", "TERMRENAMER_TMDB_API_KEY=explicit-key\n")

    settings = load_settings(env_file=explicit)

    assert settings.tmdb_api_key == "explicit-key"
    assert settings.omdb_api_key is None
    assert settings.tvdb_api_key is None


def test_environment_still_overrides_the_explicit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "env-key")
    explicit = _write(tmp_path / "explicit.env", "TERMRENAMER_TMDB_API_KEY=explicit-key\n")

    assert load_settings(env_file=explicit).tmdb_api_key == "env-key"


def test_a_loaded_file_does_not_leak_into_a_later_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = _write(tmp_path / "explicit.env", "TERMRENAMER_TMDB_API_KEY=explicit-key\n")
    load_settings(env_file=explicit)
    monkeypatch.setenv("TERMRENAMER_OMDB_API_KEY", "made-up-omdb")

    settings = load_settings()

    assert settings.tmdb_api_key is None


def _rule_case(
    platform: str,
    env: dict[str, str | None],
    expected_parts: tuple[str, ...],
    dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(sys, "platform", platform)
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return dirs.home.joinpath(*expected_parts, "termrenamer", ".env")


@pytest.mark.parametrize(
    ("platform", "env", "expected_parts"),
    [
        pytest.param(
            "win32",
            {"APPDATA": "{home}/Roaming-elsewhere", "XDG_CONFIG_HOME": "{home}/xdg"},
            ("Roaming-elsewhere",),
            id="windows-appdata",
        ),
        pytest.param(
            "win32",
            {"APPDATA": None, "XDG_CONFIG_HOME": "{home}/xdg"},
            ("AppData", "Roaming"),
            id="windows-appdata-unset",
        ),
        pytest.param(
            "win32",
            {"APPDATA": "", "XDG_CONFIG_HOME": "{home}/xdg"},
            ("AppData", "Roaming"),
            id="windows-appdata-empty",
        ),
        pytest.param(
            "linux",
            {"XDG_CONFIG_HOME": "{home}/xdg", "APPDATA": "{home}/appdata"},
            ("xdg",),
            id="linux-xdg",
        ),
        pytest.param(
            "darwin",
            {"XDG_CONFIG_HOME": "{home}/xdg", "APPDATA": "{home}/appdata"},
            ("xdg",),
            id="macos-xdg",
        ),
        pytest.param(
            "darwin",
            {"XDG_CONFIG_HOME": None, "APPDATA": "{home}/appdata"},
            (".config",),
            id="macos-xdg-unset",
        ),
        pytest.param(
            "linux",
            {"XDG_CONFIG_HOME": "", "APPDATA": "{home}/appdata"},
            (".config",),
            id="linux-xdg-empty",
        ),
        pytest.param(
            "linux",
            {"XDG_CONFIG_HOME": "relative/xdg", "APPDATA": "{home}/appdata"},
            (".config",),
            id="linux-xdg-relative-ignored",
        ),
    ],
)
def test_user_settings_file_location_follows_the_platform_rule(
    platform: str,
    env: dict[str, str | None],
    expected_parts: tuple[str, ...],
    isolated_settings_dirs: IsolatedDirs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = str(isolated_settings_dirs.home)
    resolved_env = {k: None if v is None else v.replace("{home}", home) for k, v in env.items()}
    expected = _rule_case(
        platform, resolved_env, expected_parts, isolated_settings_dirs, monkeypatch
    )
    _write(expected, "TERMRENAMER_TMDB_API_KEY=found-here\n")

    settings = load_settings()

    assert settings.tmdb_api_key == "found-here"


def test_missing_tmdb_key_message_names_the_user_settings_file(
    isolated_settings_dirs: IsolatedDirs,
) -> None:
    expected = isolated_settings_dirs.user_settings_file

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    message = str(excinfo.value)
    assert "TERMRENAMER_TMDB_API_KEY" in message
    assert str(expected) in message


def test_missing_tmdb_key_message_follows_the_windows_rule(
    isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    expected = isolated_settings_dirs.appdata / "termrenamer" / ".env"

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    assert str(expected) in str(excinfo.value)


def _wiring_without_optional_providers() -> PlanningWiring:
    return PlanningWiring(
        tv_tmdb=StaticTvMetadataProvider(_mapping={}),
        tv_tvdb=None,
        film=StaticFilmMetadataProvider(_mapping={}),
        film_omdb=None,
    )


def test_missing_tvdb_key_message_names_the_user_settings_file(
    isolated_settings_dirs: IsolatedDirs,
) -> None:
    expected = isolated_settings_dirs.user_settings_file

    with pytest.raises(ValidationError) as excinfo:
        _wiring_without_optional_providers().resolve_tv(provider_id="tvdb")

    assert "TERMRENAMER_TVDB_API_KEY" in str(excinfo.value)
    assert str(expected) in str(excinfo.value)


def test_missing_omdb_key_message_names_the_user_settings_file(
    isolated_settings_dirs: IsolatedDirs,
) -> None:
    expected = isolated_settings_dirs.user_settings_file

    with pytest.raises(ValidationError) as excinfo:
        _wiring_without_optional_providers().resolve_film(provider_id="omdb")

    assert "TERMRENAMER_OMDB_API_KEY" in str(excinfo.value)
    assert str(expected) in str(excinfo.value)


def test_wrong_value_in_user_settings_file_gives_the_validation_message(
    isolated_settings_dirs: IsolatedDirs,
) -> None:
    _write(
        isolated_settings_dirs.user_settings_file,
        "TERMRENAMER_TMDB_API_KEY=k\nTERMRENAMER_ENABLE_FOLDER_RENAME=maybe\n",
    )

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    assert "TERMRENAMER_ENABLE_FOLDER_RENAME" in str(excinfo.value)


def test_unreadable_user_settings_file_gives_a_validation_error_naming_it(
    isolated_settings_dirs: IsolatedDirs,
) -> None:
    user_file = isolated_settings_dirs.user_settings_file
    user_file.parent.mkdir(parents=True)
    user_file.write_bytes(b"TERMRENAMER_TMDB_API_KEY=\xff\xfe\n")

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    assert str(user_file) in str(excinfo.value)


@pytest.mark.parametrize(
    "variable",
    [
        "TERMRENAMER_TV_DEST_FOLDER",
        "TERMRENAMER_FILM_DEST_FOLDER",
        "TERMRENAMER_CACHE_DB_PATH",
        "TERMRENAMER_LOG_FILE",
    ],
)
def test_a_path_with_an_unknown_user_is_a_validation_error_naming_its_variable(
    variable: str, isolated_settings_dirs: IsolatedDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~someone/TV`` for a user the system does not know stops the start with exit
    status 2, as an invalid value does, instead of an unhandled error."""
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "a-test-key")
    monkeypatch.setenv(variable, "~nonexistent-user-of-termrenamer/TV")

    with pytest.raises(ValidationError) as raised:
        load_settings()

    assert str(raised.value).startswith(f"{variable} cannot be used:")
