"""SQLite schema for the lookup cache (implementation detail).

Every entry is keyed by Provider. A file with another schema version has its
tables dropped and made again on open; nothing is migrated.
"""

from __future__ import annotations

# Bump when the on-disk layout changes. Version 1 held tv_lookup and film_lookup,
# keyed by hint only; version 2 keys every entry by Provider.
SCHEMA_VERSION = 2

DDL_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
"""

# Sentinel for "no year hint" (a primary key column cannot rely on SQL NULL).
YEAR_HINT_NONE_KEY = -2_147_483_648

# One row per search: the ordered results as a JSON list of Candidates.
DDL_SEARCH_LOOKUP = """
CREATE TABLE IF NOT EXISTS search_lookup (
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    hint_norm TEXT NOT NULL,
    year_hint_key INTEGER NOT NULL,
    results TEXT NOT NULL,
    PRIMARY KEY (provider, mode, hint_norm, year_hint_key)
);
"""

DDL_EPISODE_LOOKUP = """
CREATE TABLE IF NOT EXISTS episode_lookup (
    provider TEXT NOT NULL,
    show_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    episode_title TEXT NOT NULL,
    PRIMARY KEY (provider, show_id, season, episode)
);
"""


# Every table any schema version made, dropped when the version changes.
CACHE_TABLES = ("schema_meta", "tv_lookup", "film_lookup", "search_lookup", "episode_lookup")


def all_ddl() -> tuple[str, ...]:
    """Return DDL statements in safe application order."""
    return (DDL_SCHEMA_META, DDL_SEARCH_LOOKUP, DDL_EPISODE_LOOKUP)
