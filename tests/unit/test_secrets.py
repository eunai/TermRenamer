"""Secret hygiene and settings validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.app_bootstrap import load_settings
from termrenamer.util.errors import ValidationError


def test_missing_tmdb_key_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Use an empty dotenv file so `load_settings` does not pull keys from the repo `.env`."""
    monkeypatch.delenv("TERMRENAMER_TMDB_API_KEY", raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError) as excinfo:
        load_settings(env_file=empty_env, require_tmdb_key=True)
    assert "TERMRENAMER_TMDB_API_KEY" in str(excinfo.value)


def test_present_key_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "test_key_value")
    settings = load_settings(require_tmdb_key=True)
    assert settings.tmdb_api_key == "test_key_value"


def test_dest_folder_env_vars_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.setenv("TERMRENAMER_FILM_DEST_FOLDER", str(tmp_path / "films"))
    monkeypatch.setenv("TERMRENAMER_TV_DEST_FOLDER", str(tmp_path / "tv"))
    settings = load_settings(require_tmdb_key=True)
    assert settings.film_dest_folder == tmp_path / "films"
    assert settings.tv_dest_folder == tmp_path / "tv"


def test_gitignore_contains_env(tmp_path: Path) -> None:
    del tmp_path  # repo root check
    root = Path(__file__).resolve().parents[2]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text
