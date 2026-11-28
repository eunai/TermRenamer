"""The Theme setting: ``TERMRENAMER_THEME`` chooses the dark or the light teal palette."""

from __future__ import annotations

import pytest

from termrenamer.app_bootstrap import ThemeName, load_settings
from termrenamer.util.errors import ValidationError


def test_the_theme_is_dark_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")

    assert load_settings().theme is ThemeName.DARK


@pytest.mark.parametrize(
    ("raw", "theme"),
    [
        ("dark", ThemeName.DARK),
        ("light", ThemeName.LIGHT),
        (" Light ", ThemeName.LIGHT),
        ("", ThemeName.DARK),
    ],
)
def test_the_theme_takes_dark_or_light(
    raw: str, theme: ThemeName, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_THEME", raw)

    assert load_settings().theme is theme


def test_any_other_theme_is_a_validation_error_naming_the_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_THEME", "gruvbox")

    with pytest.raises(ValidationError, match="TERMRENAMER_THEME.*dark.*light"):
        load_settings()


def test_main_exits_2_on_an_invalid_theme(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from termrenamer.__main__ import main

    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_THEME", "blue")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 2
    assert "TERMRENAMER_THEME" in capsys.readouterr().err
