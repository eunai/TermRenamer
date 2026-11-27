"""The Name taken setting: ``TERMRENAMER_NAME_TAKEN`` is ``suffix`` (the default) or ``skip``."""

from __future__ import annotations

import pytest

from termrenamer.app_bootstrap import load_settings
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.util.errors import ValidationError


def test_name_taken_adds_a_number_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")

    assert load_settings().name_taken is NameTakenPolicy.SUFFIX


@pytest.mark.parametrize(
    ("raw", "policy"),
    [
        ("suffix", NameTakenPolicy.SUFFIX),
        ("skip", NameTakenPolicy.SKIP),
        (" Skip ", NameTakenPolicy.SKIP),
        ("", NameTakenPolicy.SUFFIX),
    ],
)
def test_name_taken_takes_suffix_or_skip(
    raw: str, policy: NameTakenPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_NAME_TAKEN", raw)

    assert load_settings().name_taken is policy


def test_any_other_name_taken_value_is_a_validation_error_naming_the_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_NAME_TAKEN", "overwrite")

    with pytest.raises(ValidationError, match="TERMRENAMER_NAME_TAKEN.*suffix.*skip"):
        load_settings()


def test_main_exits_2_on_an_invalid_name_taken_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from termrenamer.__main__ import main

    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_NAME_TAKEN", "number")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 2
    assert "TERMRENAMER_NAME_TAKEN" in capsys.readouterr().err
