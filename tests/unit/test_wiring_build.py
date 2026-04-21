"""Integration-style tests for :func:`termrenamer.wiring.build_planning_wiring`."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.app_bootstrap import Settings, create_http_client
from termrenamer.util.errors import ValidationError
from termrenamer.wiring import build_planning_wiring


def _settings(
    *,
    tmp_path: Path | None = None,
    tvdb_key: str | None = None,
    tvdb_pin: str | None = None,
    tmdb_key: str = "tmdb-test-key",
    omdb_key: str | None = None,
) -> Settings:
    cache = tmp_path / "cache.db" if tmp_path is not None else None
    return Settings(
        tmdb_api_key=tmdb_key,
        tvdb_api_key=tvdb_key,
        tvdb_subscriber_pin=tvdb_pin,
        omdb_api_key=omdb_key,
        http_timeout_seconds=30.0,
        http_max_attempts=4,
        http_backoff_base_seconds=0.5,
        http_jitter=True,
        cache_db_path=cache,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=None,
    )


def test_build_planning_wiring_requires_tmdb() -> None:
    http = create_http_client(_settings())
    bad = _settings(tmdb_key="")
    bad = Settings(
        tmdb_api_key=None,
        tvdb_api_key=None,
        tvdb_subscriber_pin=None,
        omdb_api_key=None,
        http_timeout_seconds=30.0,
        http_max_attempts=4,
        http_backoff_base_seconds=0.5,
        http_jitter=True,
        cache_db_path=None,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=None,
    )
    with pytest.raises(ValidationError, match="TMDB API key"):
        build_planning_wiring(bad, http)


def test_build_planning_wiring_no_cache_no_tvdb(tmp_path: Path) -> None:
    s = _settings(tmp_path=None)
    http = create_http_client(s)
    w = build_planning_wiring(s, http)
    assert w.tv_tvdb is None
    assert w.tv_tmdb is not None
    assert w.film is not None


def test_build_planning_wiring_with_cache_and_tvdb(tmp_path: Path) -> None:
    s = _settings(tmp_path=tmp_path, tvdb_key="tvdb-key", tvdb_pin="pin")
    http = create_http_client(s)
    w = build_planning_wiring(s, http)
    assert w.tv_tvdb is not None


def test_build_planning_wiring_with_omdb(tmp_path: Path) -> None:
    s = _settings(omdb_key="omdb-key")
    http = create_http_client(s)
    w = build_planning_wiring(s, http)
    assert w.film_omdb is not None


def test_build_planning_wiring_no_omdb() -> None:
    s = _settings(omdb_key=None)
    http = create_http_client(s)
    w = build_planning_wiring(s, http)
    assert w.film_omdb is None


def test_bootstrap_wiring_returns_tuple(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMRENAMER_TMDB_API_KEY", "k")
    monkeypatch.delenv("TERMRENAMER_TVDB_API_KEY", raising=False)
    monkeypatch.setenv("TERMRENAMER_CACHE_DB_PATH", str(tmp_path / "c.db"))
    from termrenamer.wiring import bootstrap_wiring

    settings, wiring = bootstrap_wiring()
    assert settings.tmdb_api_key == "k"
    assert wiring.tv_tmdb is not None
