"""SQLite-backed metadata lookup cache (optional acceleration; spec §12.6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.persistence import schema
from termrenamer.persistence.sqlite import init_schema, open_cache_connection
from termrenamer.util.errors import CacheError


def _norm_show(s: str) -> str:
    return s.casefold().strip()


def _film_year_key(year_hint: int | None) -> int:
    return year_hint if year_hint is not None else schema.YEAR_HINT_NONE_KEY


class SqliteMetadataCache:
    """Persist TV and film metadata lookups; safe to delete the file (performance only)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = open_cache_connection(self._path)
            init_schema(conn)
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata | None:
        """Return cached TV metadata or ``None`` on miss."""
        key = _norm_show(show_hint)
        try:
            row = (
                self._connection()
                .execute(
                    """
                SELECT show_title, episode_title FROM tv_lookup
                WHERE show_hint_norm = ? AND season = ? AND episode = ?
                """,
                    (key, season, episode),
                )
                .fetchone()
            )
        except sqlite3.Error as exc:
            msg = "SQLite read failed for TV cache"
            raise CacheError(msg) from exc
        if row is None:
            return None
        return EpisodeMetadata(show_title=row["show_title"], episode_title=row["episode_title"])

    def put_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
        metadata: EpisodeMetadata,
    ) -> None:
        key = _norm_show(show_hint)
        try:
            self._connection().execute(
                """
                INSERT INTO tv_lookup (show_hint_norm, season, episode, show_title, episode_title)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(show_hint_norm, season, episode) DO UPDATE SET
                    show_title = excluded.show_title,
                    episode_title = excluded.episode_title
                """,
                (key, season, episode, metadata.show_title, metadata.episode_title),
            )
            self._connection().commit()
        except sqlite3.Error as exc:
            msg = "SQLite write failed for TV cache"
            raise CacheError(msg) from exc

    def get_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata | None:
        """Return cached film metadata or ``None`` on miss."""
        key = _norm_show(title_hint)
        yk = _film_year_key(year_hint)
        try:
            row = (
                self._connection()
                .execute(
                    """
                SELECT resolved_title, resolved_year FROM film_lookup
                WHERE title_hint_norm = ? AND year_hint_key = ?
                """,
                    (key, yk),
                )
                .fetchone()
            )
        except sqlite3.Error as exc:
            msg = "SQLite read failed for film cache"
            raise CacheError(msg) from exc
        if row is None:
            return None
        return MovieMetadata(title=row["resolved_title"], year=int(row["resolved_year"]))

    def put_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
        metadata: MovieMetadata,
    ) -> None:
        key = _norm_show(title_hint)
        yk = _film_year_key(year_hint)
        try:
            self._connection().execute(
                """
                INSERT INTO film_lookup (
                    title_hint_norm, year_hint_key, resolved_title, resolved_year
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(title_hint_norm, year_hint_key) DO UPDATE SET
                    resolved_title = excluded.resolved_title,
                    resolved_year = excluded.resolved_year
                """,
                (key, yk, metadata.title, metadata.year),
            )
            self._connection().commit()
        except sqlite3.Error as exc:
            msg = "SQLite write failed for film cache"
            raise CacheError(msg) from exc
