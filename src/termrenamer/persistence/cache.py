"""SQLite-backed lookup cache (optional acceleration; safe to delete)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from termrenamer.core.models import Candidate, ScanMode
from termrenamer.persistence import schema
from termrenamer.persistence.sqlite import init_schema, open_cache_connection
from termrenamer.util.errors import CacheError


def normalise_hint(hint: str) -> str:
    """The form a title hint is keyed by: case folded, outer spaces removed."""
    return hint.casefold().strip()


def _year_key(year: int | None) -> int:
    return year if year is not None else schema.YEAR_HINT_NONE_KEY


def _encode(results: tuple[Candidate, ...]) -> str:
    return json.dumps(
        [{"id": c.id, "name": c.name, "year": c.year, "poster_ref": c.poster_ref} for c in results]
    )


def _decode(text: str) -> tuple[Candidate, ...]:
    try:
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise TypeError("stored results are not a list")
        return tuple(
            Candidate(
                id=str(row["id"]),
                name=str(row["name"]),
                year=None if row["year"] is None else int(row["year"]),
                poster_ref=None if row["poster_ref"] is None else str(row["poster_ref"]),
            )
            for row in rows
        )
    except (ValueError, TypeError, KeyError) as exc:
        msg = "Unreadable search entry in SQLite cache"
        raise CacheError(msg) from exc


class SqliteMetadataCache:
    """Store search results and episode titles, every entry keyed by Provider.

    Search results are keyed by Provider, Mode, normalised hint and year hint;
    episode titles by Provider, show id, season and episode. One connection serves
    every thread, one operation at a time.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = open_cache_connection(self._path)
            try:
                init_schema(conn)
            except CacheError:
                conn.close()
                raise
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __del__(self) -> None:
        """Best-effort close; prefer explicit :meth:`close` in app/teardown code."""

        self.close()

    def get_search(
        self,
        *,
        provider: str,
        mode: ScanMode,
        hint: str,
        year: int | None,
    ) -> tuple[Candidate, ...] | None:
        """Return the stored results of a search, or ``None`` when none is stored."""
        key = (provider, mode.value, normalise_hint(hint), _year_key(year))
        with self._lock:
            try:
                row = (
                    self._connection()
                    .execute(
                        """
                        SELECT results FROM search_lookup
                        WHERE provider = ? AND mode = ? AND hint_norm = ? AND year_hint_key = ?
                        """,
                        key,
                    )
                    .fetchone()
                )
            except sqlite3.Error as exc:
                msg = "SQLite read failed for search cache"
                raise CacheError(msg) from exc
        return None if row is None else _decode(row["results"])

    def put_search(
        self,
        *,
        provider: str,
        mode: ScanMode,
        hint: str,
        year: int | None,
        results: tuple[Candidate, ...],
    ) -> None:
        """Store a search's results (the caller stores nothing for "nothing found")."""
        key = (provider, mode.value, normalise_hint(hint), _year_key(year))
        self._write(
            """
            INSERT INTO search_lookup (provider, mode, hint_norm, year_hint_key, results)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, mode, hint_norm, year_hint_key) DO UPDATE SET
                results = excluded.results
            """,
            (*key, _encode(results)),
            what="search",
        )

    def get_episode(
        self,
        *,
        provider: str,
        show_id: str,
        season: int,
        episode: int,
    ) -> str | None:
        """Return the stored episode title, or ``None`` when none is stored."""
        with self._lock:
            try:
                row = (
                    self._connection()
                    .execute(
                        """
                        SELECT episode_title FROM episode_lookup
                        WHERE provider = ? AND show_id = ? AND season = ? AND episode = ?
                        """,
                        (provider, show_id, season, episode),
                    )
                    .fetchone()
                )
            except sqlite3.Error as exc:
                msg = "SQLite read failed for episode cache"
                raise CacheError(msg) from exc
        return None if row is None else str(row["episode_title"])

    def put_episode(
        self,
        *,
        provider: str,
        show_id: str,
        season: int,
        episode: int,
        title: str,
    ) -> None:
        """Store an episode title."""
        self._write(
            """
            INSERT INTO episode_lookup (provider, show_id, season, episode, episode_title)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, show_id, season, episode) DO UPDATE SET
                episode_title = excluded.episode_title
            """,
            (provider, show_id, season, episode, title),
            what="episode",
        )

    def _write(self, sql: str, params: tuple[object, ...], *, what: str) -> None:
        with self._lock:
            try:
                conn = self._connection()
                conn.execute(sql, params)
                conn.commit()
            except sqlite3.Error as exc:
                msg = f"SQLite write failed for {what} cache"
                raise CacheError(msg) from exc
