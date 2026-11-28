"""Start-up with any one Provider key: settings loading and the entry point."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from termrenamer.app_bootstrap import load_settings, user_settings_path
from termrenamer.util.errors import ValidationError

_KEY_VARIABLES = (
    "TERMRENAMER_TMDB_API_KEY",
    "TERMRENAMER_TVDB_API_KEY",
    "TERMRENAMER_OMDB_API_KEY",
)


@pytest.mark.parametrize("variable", _KEY_VARIABLES)
def test_any_one_provider_key_is_enough_to_load(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(variable, "made-up-key")

    settings = load_settings()

    keys = (settings.tmdb_api_key, settings.tvdb_api_key, settings.omdb_api_key)
    assert keys.count("made-up-key") == 1
    assert keys.count(None) == 2


def test_no_provider_key_names_the_three_variables_and_where_to_set_them() -> None:
    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    message = str(excinfo.value)
    for variable in _KEY_VARIABLES:
        assert variable in message
    assert "one is enough" in message
    assert str(user_settings_path()) in message
    assert ".env" in message


def test_a_tvdb_pin_alone_is_not_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TVDB_SUBSCRIBER_PIN", "made-up-pin")

    with pytest.raises(ValidationError, match="one is enough"):
        load_settings()


def test_blank_keys_count_as_not_set(tmp_path: Path) -> None:
    explicit = tmp_path / "blank.env"
    explicit.write_text(
        "TERMRENAMER_TMDB_API_KEY=\nTERMRENAMER_TVDB_API_KEY=   \nTERMRENAMER_OMDB_API_KEY=\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="one is enough"):
        load_settings(env_file=explicit)


def test_main_with_no_provider_key_exits_2_with_the_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from termrenamer import __main__ as main_mod

    with pytest.raises(SystemExit) as excinfo:
        main_mod.main()

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    for variable in _KEY_VARIABLES:
        assert variable in err
    assert "one is enough" in err


@pytest.mark.parametrize("variable", _KEY_VARIABLES)
def test_main_starts_the_app_with_any_one_provider_key(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from termrenamer import __main__ as main_mod

    monkeypatch.setenv(variable, "made-up-key")

    class Started(Exception):
        pass

    with (
        mock.patch("termrenamer.tui.app.TermRenamerApp.run", side_effect=Started),
        pytest.raises(Started),
    ):
        main_mod.main()
