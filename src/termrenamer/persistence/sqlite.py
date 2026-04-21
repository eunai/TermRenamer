"""SQLite connection helpers for the metadata cache."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from termrenamer.persistence import schema
from termrenamer.util.errors import CacheError


def open_cache_connection(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL; create parent dirs when needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30.0)
    except OSError as exc:
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


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply DDL and record schema version."""
    try:
        for stmt in schema.all_ddl():
            conn.execute(stmt)
        row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (schema.SCHEMA_VERSION,))
        conn.commit()
    except sqlite3.Error as exc:
        msg = "SQLite schema initialization failed"
        raise CacheError(msg) from exc
