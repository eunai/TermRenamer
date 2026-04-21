"""SQLite schema for metadata cache (implementation detail; spec §7)."""

from __future__ import annotations

# Bump when on-disk layout changes; see CHANGELOG Operational notes.
SCHEMA_VERSION = 1

DDL_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
"""

DDL_TV_LOOKUP = """
CREATE TABLE IF NOT EXISTS tv_lookup (
    show_hint_norm TEXT NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    show_title TEXT NOT NULL,
    episode_title TEXT NOT NULL,
    PRIMARY KEY (show_hint_norm, season, episode)
);
"""

# Sentinel for ``year_hint is None`` (SQLite PK cannot use SQL NULL reliably for all rows).
YEAR_HINT_NONE_KEY = -2_147_483_648

DDL_FILM_LOOKUP = """
CREATE TABLE IF NOT EXISTS film_lookup (
    title_hint_norm TEXT NOT NULL,
    year_hint_key INTEGER NOT NULL,
    resolved_title TEXT NOT NULL,
    resolved_year INTEGER NOT NULL,
    PRIMARY KEY (title_hint_norm, year_hint_key)
);
"""


def all_ddl() -> tuple[str, ...]:
    """Return DDL statements in safe application order."""
    return (DDL_SCHEMA_META, DDL_TV_LOOKUP, DDL_FILM_LOOKUP)
