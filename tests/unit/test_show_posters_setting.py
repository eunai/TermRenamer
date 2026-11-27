"""The Show posters setting: ``TERMRENAMER_SHOW_POSTERS``, and the session's value of it."""

from __future__ import annotations

import pytest

from termrenamer.app_bootstrap import load_settings
from termrenamer.core.models import ScanMode
from termrenamer.session_settings import SessionSettings
from termrenamer.util.errors import ValidationError


def test_posters_are_shown_when_the_setting_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")

    assert load_settings().show_posters is True


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        (" No ", False),
        ("off", False),
        ("", True),
    ],
)
def test_the_setting_takes_the_boolean_words(
    raw: str, shown: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_SHOW_POSTERS", raw)

    assert load_settings().show_posters is shown


def test_any_other_value_is_a_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_SHOW_POSTERS", "sometimes")

    with pytest.raises(ValidationError, match="TERMRENAMER_SHOW_POSTERS"):
        load_settings()


def test_main_exits_2_on_an_invalid_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from termrenamer.__main__ import main

    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_SHOW_POSTERS", "maybe")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 2
    assert "TERMRENAMER_SHOW_POSTERS" in capsys.readouterr().err


def test_the_session_starts_with_the_loaded_value_and_changes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_SHOW_POSTERS", "false")
    owner = SessionSettings(load_settings())
    plan_heard: list[str] = []
    posters_heard: list[bool] = []
    owner.add_listener(plan_heard.append)
    owner.add_poster_listener(posters_heard.append)

    assert owner.show_posters is False
    assert owner.set_show_posters(True) is True
    assert owner.set_show_posters(True) is False

    assert owner.show_posters is True
    assert posters_heard == [True]
    assert plan_heard == []


def test_show_posters_changes_while_a_plan_is_built() -> None:
    """``i`` works at every Stage, the Plan Stage included; no Plan depends on it."""
    owner = SessionSettings(None)
    owner.lock()

    assert owner.set_show_posters(False) is True
    assert owner.show_posters is False
    assert owner.plan_options().mode is ScanMode.TV
