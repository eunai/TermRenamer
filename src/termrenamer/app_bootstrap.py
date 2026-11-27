"""Load settings, logging, and construct app wiring."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values

from termrenamer.core.policies import NameTakenPolicy
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import ValidationError
from termrenamer.util.http import HttpClient, HttpClientConfig
from termrenamer.util.logging import setup_logging

_LOG = logging.getLogger(__name__)


class ThemeName(StrEnum):
    """The screen's palette: the dark or the light teal theme (``TERMRENAMER_THEME``)."""

    DARK = "dark"
    LIGHT = "light"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration; constructed once at bootstrap."""

    tmdb_api_key: str | None
    tvdb_api_key: str | None
    tvdb_subscriber_pin: str | None
    omdb_api_key: str | None
    http_timeout_seconds: float
    http_max_attempts: int
    http_backoff_base_seconds: float
    http_jitter: bool
    cache_db_path: Path | None
    log_file_path: Path | None
    film_dest_folder: Path | None
    tv_dest_folder: Path | None
    enable_folder_rename: bool
    enable_season_folders: bool
    theme: ThemeName = ThemeName.DARK
    name_taken: NameTakenPolicy = NameTakenPolicy.SUFFIX
    show_posters: bool = True

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_api_key and self.tmdb_api_key.strip())

    @property
    def has_tvdb_credentials(self) -> bool:
        return bool(self.tvdb_api_key and self.tvdb_api_key.strip())

    @property
    def has_omdb_credentials(self) -> bool:
        return bool(self.omdb_api_key and self.omdb_api_key.strip())


def _read_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        msg = f"Invalid numeric value for {name}"
        raise ValidationError(msg) from exc


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"Invalid integer value for {name}"
        raise ValidationError(msg) from exc


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    msg = f"Invalid boolean value for {name} (use true/false)"
    raise ValidationError(msg)


def _read_theme(env: Mapping[str, str]) -> ThemeName:
    raw = env.get("TERMRENAMER_THEME")
    if raw is None or raw.strip() == "":
        return ThemeName.DARK
    try:
        return ThemeName(raw.strip().lower())
    except ValueError as exc:
        msg = "Invalid value for TERMRENAMER_THEME (use dark or light)"
        raise ValidationError(msg) from exc


def _read_name_taken(env: Mapping[str, str]) -> NameTakenPolicy:
    raw = env.get("TERMRENAMER_NAME_TAKEN")
    if raw is None or raw.strip() == "":
        return NameTakenPolicy.SUFFIX
    try:
        return NameTakenPolicy(raw.strip().lower())
    except ValueError as exc:
        msg = "Invalid value for TERMRENAMER_NAME_TAKEN (use suffix or skip)"
        raise ValidationError(msg) from exc


def user_settings_path() -> Path:
    """Return the path of the user settings file for this platform and environment.

    Windows: ``%APPDATA%\\termrenamer\\.env``, or ``AppData\\Roaming`` in the home folder
    when ``APPDATA`` is unset or empty. Every other platform, macOS included:
    ``$XDG_CONFIG_HOME/termrenamer/.env``, or ``~/.config`` when ``XDG_CONFIG_HOME`` is
    unset, empty or relative (the XDG Base Directory rule). The app never writes this file.
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", ""))
        base = xdg if xdg.is_absolute() else Path.home() / ".config"
    return base / "termrenamer" / ".env"


def _read_settings_file(path: Path) -> dict[str, str]:
    """Return the values a dotenv file sets; a missing file sets none."""
    try:
        values = dotenv_values(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"Cannot read settings file {path}: {exc}"
        raise ValidationError(msg) from exc
    return {k: v for k, v in values.items() if v is not None}


def _layer(*sources: Mapping[str, str]) -> dict[str, str]:
    """Merge sources given lowest first; a blank value never hides a lower source's value."""
    merged: dict[str, str] = {}
    for source in sources:
        for name, value in source.items():
            if value.strip() != "" or name not in merged:
                merged[name] = value
    return merged


def where_to_set(variable: str) -> str:
    """Name every place ``variable`` can be set, for a missing-setting message."""
    return (
        f"set {variable} in the environment, in a .env file in the current folder, "
        f"or in the user settings file at {user_settings_path()} (see .env.example)"
    )


def load_settings(*, env_file: Path | None = None) -> Settings:
    """Load settings from the environment and the settings files.

    Sources, highest first: environment variables, a ``.env`` in the current working
    folder (that folder only, no upward search), then the user settings file
    (:func:`user_settings_path`). A higher source's value wins; a blank value counts as
    not set, so it never hides a lower source's value. Files are only read.

    Args:
        env_file: If provided, the only file read; environment variables still win.

    Raises:
        ValidationError: No Provider key (TMDB, TheTVDB or OMDb) is set, or a value is
            invalid. A TheTVDB subscriber PIN alone is not a key.
    """
    files = [env_file] if env_file is not None else [user_settings_path(), Path.cwd() / ".env"]
    env = _layer(*(_read_settings_file(path) for path in files), os.environ)

    tmdb_key = env.get("TERMRENAMER_TMDB_API_KEY")
    if tmdb_key is not None:
        tmdb_key = tmdb_key.strip()
        if tmdb_key == "":
            tmdb_key = None

    tvdb_key = env.get("TERMRENAMER_TVDB_API_KEY")
    if tvdb_key is not None:
        tvdb_key = tvdb_key.strip()
        if tvdb_key == "":
            tvdb_key = None

    tvdb_pin = env.get("TERMRENAMER_TVDB_SUBSCRIBER_PIN")
    if tvdb_pin is not None:
        tvdb_pin = tvdb_pin.strip()
        if tvdb_pin == "":
            tvdb_pin = None

    omdb_key = env.get("TERMRENAMER_OMDB_API_KEY")
    if omdb_key is not None:
        omdb_key = omdb_key.strip()
        if omdb_key == "":
            omdb_key = None

    timeout = _read_float(env, "TERMRENAMER_HTTP_TIMEOUT_SECONDS", 30.0)
    http_max_attempts = _read_int(env, "TERMRENAMER_HTTP_MAX_ATTEMPTS", 4)
    if http_max_attempts < 1:
        raise ValidationError("TERMRENAMER_HTTP_MAX_ATTEMPTS must be >= 1")
    http_backoff_base = _read_float(env, "TERMRENAMER_HTTP_BACKOFF_BASE_SECONDS", 0.5)
    http_jitter = _read_bool(env, "TERMRENAMER_HTTP_JITTER", True)
    cache_raw = env.get("TERMRENAMER_CACHE_DB_PATH")
    if cache_raw is not None:
        cache_raw = cache_raw.strip()
        if cache_raw == "":
            cache_raw = None
    cache_path = Path(cache_raw).expanduser() if cache_raw else None

    log_path_raw = env.get("TERMRENAMER_LOG_FILE")
    log_path = Path(log_path_raw).expanduser() if log_path_raw else None

    film_dest_raw = env.get("TERMRENAMER_FILM_DEST_FOLDER")
    if film_dest_raw is not None:
        film_dest_raw = film_dest_raw.strip()
        if film_dest_raw == "":
            film_dest_raw = None
    film_dest_folder = Path(film_dest_raw).expanduser() if film_dest_raw else None

    tv_dest_raw = env.get("TERMRENAMER_TV_DEST_FOLDER")
    if tv_dest_raw is not None:
        tv_dest_raw = tv_dest_raw.strip()
        if tv_dest_raw == "":
            tv_dest_raw = None
    tv_dest_folder = Path(tv_dest_raw).expanduser() if tv_dest_raw else None

    enable_folder_rename = _read_bool(env, "TERMRENAMER_ENABLE_FOLDER_RENAME", default=False)
    enable_season_folders = _read_bool(env, "TERMRENAMER_ENABLE_SEASON_FOLDERS", default=False)
    theme = _read_theme(env)
    name_taken = _read_name_taken(env)
    show_posters = _read_bool(env, "TERMRENAMER_SHOW_POSTERS", default=True)

    if not (tmdb_key or tvdb_key or omdb_key):
        variables = "TERMRENAMER_TMDB_API_KEY, TERMRENAMER_TVDB_API_KEY or TERMRENAMER_OMDB_API_KEY"
        msg = f"No Provider API key is set, and one is enough: {where_to_set(variables)}."
        raise ValidationError(msg)

    return Settings(
        tmdb_api_key=tmdb_key,
        tvdb_api_key=tvdb_key,
        tvdb_subscriber_pin=tvdb_pin,
        omdb_api_key=omdb_key,
        http_timeout_seconds=timeout,
        http_max_attempts=http_max_attempts,
        http_backoff_base_seconds=http_backoff_base,
        http_jitter=http_jitter,
        cache_db_path=cache_path,
        log_file_path=log_path,
        film_dest_folder=film_dest_folder,
        tv_dest_folder=tv_dest_folder,
        enable_folder_rename=enable_folder_rename,
        enable_season_folders=enable_season_folders,
        theme=theme,
        name_taken=name_taken,
        show_posters=show_posters,
    )


def http_client_config_from_settings(settings: Settings) -> HttpClientConfig:
    """Build HTTP transport config from loaded settings."""
    return HttpClientConfig(
        timeout_seconds=settings.http_timeout_seconds,
        max_attempts=settings.http_max_attempts,
        backoff_base_seconds=settings.http_backoff_base_seconds,
        jitter=settings.http_jitter,
    )


def create_http_client(settings: Settings) -> HttpClient:
    """Create a shared ``HttpClient`` for provider adapters."""
    return HttpClient(config=http_client_config_from_settings(settings))


def create_metadata_cache(settings: Settings) -> SqliteMetadataCache | None:
    """Return a SQLite cache when ``TERMRENAMER_CACHE_DB_PATH`` is set."""
    if settings.cache_db_path is None:
        return None
    return SqliteMetadataCache(settings.cache_db_path)


def bootstrap() -> Settings:
    """Configure logging and return settings."""
    setup_logging()
    settings = load_settings()
    if settings.log_file_path is not None:
        _LOG.debug("File logging path configured: %s", settings.log_file_path)
    return settings
