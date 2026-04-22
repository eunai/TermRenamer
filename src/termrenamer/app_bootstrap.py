"""Load settings, logging, and construct app wiring."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import ValidationError
from termrenamer.util.http import HttpClient, HttpClientConfig
from termrenamer.util.logging import setup_logging

_LOG = logging.getLogger(__name__)


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

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_api_key and self.tmdb_api_key.strip())

    @property
    def has_tvdb_credentials(self) -> bool:
        return bool(self.tvdb_api_key and self.tvdb_api_key.strip())

    @property
    def has_omdb_credentials(self) -> bool:
        return bool(self.omdb_api_key and self.omdb_api_key.strip())


def _read_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        msg = f"Invalid numeric value for {name}"
        raise ValidationError(msg) from exc


def _read_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"Invalid integer value for {name}"
        raise ValidationError(msg) from exc


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    msg = f"Invalid boolean value for {name} (use true/false)"
    raise ValidationError(msg)


def load_settings(*, env_file: Path | None = None, require_tmdb_key: bool = True) -> Settings:
    """Load settings from environment; optional `.env` for local dev.

    Args:
        env_file: If provided, load this file via dotenv first.
        require_tmdb_key: When True, TMDB API key must be set (TV vertical slice).

    Raises:
        ValidationError: Missing required configuration or invalid values.
    """
    if env_file is not None:
        load_dotenv(env_file)
    else:
        load_dotenv()

    tmdb_key = os.environ.get("TERMRENAMER_TMDB_API_KEY")
    if tmdb_key is not None:
        tmdb_key = tmdb_key.strip()
        if tmdb_key == "":
            tmdb_key = None

    tvdb_key = os.environ.get("TERMRENAMER_TVDB_API_KEY")
    if tvdb_key is not None:
        tvdb_key = tvdb_key.strip()
        if tvdb_key == "":
            tvdb_key = None

    tvdb_pin = os.environ.get("TERMRENAMER_TVDB_SUBSCRIBER_PIN")
    if tvdb_pin is not None:
        tvdb_pin = tvdb_pin.strip()
        if tvdb_pin == "":
            tvdb_pin = None

    omdb_key = os.environ.get("TERMRENAMER_OMDB_API_KEY")
    if omdb_key is not None:
        omdb_key = omdb_key.strip()
        if omdb_key == "":
            omdb_key = None

    timeout = _read_float("TERMRENAMER_HTTP_TIMEOUT_SECONDS", 30.0)
    http_max_attempts = _read_int("TERMRENAMER_HTTP_MAX_ATTEMPTS", 4)
    if http_max_attempts < 1:
        raise ValidationError("TERMRENAMER_HTTP_MAX_ATTEMPTS must be >= 1")
    http_backoff_base = _read_float("TERMRENAMER_HTTP_BACKOFF_BASE_SECONDS", 0.5)
    http_jitter = _read_bool("TERMRENAMER_HTTP_JITTER", True)
    cache_raw = os.environ.get("TERMRENAMER_CACHE_DB_PATH")
    if cache_raw is not None:
        cache_raw = cache_raw.strip()
        if cache_raw == "":
            cache_raw = None
    cache_path = Path(cache_raw).expanduser() if cache_raw else None

    log_path_raw = os.environ.get("TERMRENAMER_LOG_FILE")
    log_path = Path(log_path_raw).expanduser() if log_path_raw else None

    film_dest_raw = os.environ.get("TERMRENAMER_FILM_DEST_FOLDER")
    if film_dest_raw is not None:
        film_dest_raw = film_dest_raw.strip()
        if film_dest_raw == "":
            film_dest_raw = None
    film_dest_folder = Path(film_dest_raw).expanduser() if film_dest_raw else None

    tv_dest_raw = os.environ.get("TERMRENAMER_TV_DEST_FOLDER")
    if tv_dest_raw is not None:
        tv_dest_raw = tv_dest_raw.strip()
        if tv_dest_raw == "":
            tv_dest_raw = None
    tv_dest_folder = Path(tv_dest_raw).expanduser() if tv_dest_raw else None

    enable_folder_rename = _read_bool("TERMRENAMER_ENABLE_FOLDER_RENAME", default=False)
    enable_season_folders = _read_bool("TERMRENAMER_ENABLE_SEASON_FOLDERS", default=False)

    if require_tmdb_key and not tmdb_key:
        raise ValidationError(
            "TMDB API key is required: set TERMRENAMER_TMDB_API_KEY in the environment "
            "or .env (see .env.example).",
        )

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


def bootstrap(*, require_tmdb_key: bool = True) -> Settings:
    """Configure logging and return settings."""
    setup_logging()
    settings = load_settings(require_tmdb_key=require_tmdb_key)
    if settings.log_file_path is not None:
        _LOG.debug("File logging path configured: %s", settings.log_file_path)
    return settings
