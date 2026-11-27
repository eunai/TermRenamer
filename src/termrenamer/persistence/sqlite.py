"""SQLite connection helpers for the lookup cache."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from termrenamer.persistence import schema
from termrenamer.util.errors import CacheError


def open_cache_connection(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL; create parent dirs when needed.

    The connection may be used from any thread; the caller serialises its use.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    except (OSError, sqlite3.Error) as exc:
        msg = f"Could not open SQLite cache at {path}"
        raise CacheError(msg) from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.Error as exc:
        conn.close()
        msg = f"SQLite pragma failed for {path}"
        raise CacheError(msg) from exc
    return conn


def _stored_version(conn: sqlite3.Connection) -> int | None:
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
    ).fetchone()
    if has_meta is None:
        return None
    row = conn.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
    return None if row is None or row["version"] is None else int(row["version"])


def _drop_cache_tables(conn: sqlite3.Connection) -> None:
    for name in schema.CACHE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {name}")


def init_schema(conn: sqlite3.Connection) -> None:
    """Make the tables and record the schema version.

    A file that records another schema version has the cache's tables (those of
    every version) dropped and made again: the cache is safe to delete, so nothing
    is migrated. Tables the cache never made are left alone.
    """
    try:
        version = _stored_version(conn)
        if version is not None and version != schema.SCHEMA_VERSION:
            _drop_cache_tables(conn)
        for stmt in schema.all_ddl():
            conn.execute(stmt)
        if _stored_version(conn) is None:
            conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (schema.SCHEMA_VERSION,))
        conn.commit()
    except sqlite3.Error as exc:
        msg = "SQLite schema initialization failed"
        raise CacheError(msg) from exc
