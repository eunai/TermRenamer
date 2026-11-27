"""SQLite lookup cache tests: a real file under the test's temporary folder."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from termrenamer.core.models import Candidate, ScanMode
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import CacheError

_FOUND = (
    Candidate(id="7001", name="Quiet Valley", year=2019, poster_ref="/quiet-valley.jpg"),
    Candidate(id="7002", name="Quiet Valley Stories", year=None, poster_ref=None),
)


def test_search_results_round_trip_in_order_with_posters(tmp_path: Path) -> None:
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    assert (
        cache.get_search(provider="tmdb", mode=ScanMode.TV, hint="Quiet Valley", year=None) is None
    )

    cache.put_search(
        provider="tmdb", mode=ScanMode.TV, hint="Quiet Valley", year=None, results=_FOUND
    )

    got = cache.get_search(provider="tmdb", mode=ScanMode.TV, hint="  quiet valley ", year=None)
    assert got == _FOUND
    cache.close()


def test_search_results_are_keyed_by_provider_mode_and_year(tmp_path: Path) -> None:
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    cache.put_search(provider="tmdb", mode=ScanMode.FILM, hint="Harbour", year=2011, results=_FOUND)

    assert cache.get_search(provider="omdb", mode=ScanMode.FILM, hint="Harbour", year=2011) is None
    assert cache.get_search(provider="tmdb", mode=ScanMode.TV, hint="Harbour", year=2011) is None
    assert cache.get_search(provider="tmdb", mode=ScanMode.FILM, hint="Harbour", year=None) is None
    assert cache.get_search(provider="tmdb", mode=ScanMode.FILM, hint="Harbour", year=2012) is None
    cache.close()


def test_episode_titles_round_trip_keyed_by_provider(tmp_path: Path) -> None:
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    cache.put_episode(provider="tvdb", show_id="81001", season=1, episode=2, title="Thaw")

    assert cache.get_episode(provider="tvdb", show_id="81001", season=1, episode=2) == "Thaw"
    assert cache.get_episode(provider="tmdb", show_id="81001", season=1, episode=2) is None
    assert cache.get_episode(provider="tvdb", show_id="81001", season=1, episode=3) is None
    cache.close()


def test_entries_persist_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "meta.db"
    first = SqliteMetadataCache(db)
    first.put_episode(provider="tmdb", show_id="42", season=2, episode=3, title="One")
    first.close()

    second = SqliteMetadataCache(db)
    assert second.get_episode(provider="tmdb", show_id="42", season=2, episode=3) == "One"
    second.close()


def test_a_cache_opened_on_one_thread_reads_on_another(tmp_path: Path) -> None:
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    cache.put_episode(provider="tmdb", show_id="42", season=1, episode=1, title="Pilot")
    seen: list[object] = []

    def read() -> None:
        try:
            seen.append(cache.get_episode(provider="tmdb", show_id="42", season=1, episode=1))
            cache.put_episode(provider="tmdb", show_id="42", season=1, episode=2, title="Two")
        except CacheError as exc:  # pragma: no cover - the failure this test guards
            seen.append(exc)

    worker = threading.Thread(target=read)
    worker.start()
    worker.join()

    assert seen == ["Pilot"]
    assert cache.get_episode(provider="tmdb", show_id="42", season=1, episode=2) == "Two"
    cache.close()


def _make_version_1_file(path: Path) -> None:
    """Write a cache file the way schema version 1 laid it out, with one entry."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER NOT NULL);
        INSERT INTO schema_meta (version) VALUES (1);
        CREATE TABLE tv_lookup (
            show_hint_norm TEXT NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
            show_title TEXT NOT NULL, episode_title TEXT NOT NULL,
            PRIMARY KEY (show_hint_norm, season, episode)
        );
        INSERT INTO tv_lookup VALUES ('quiet valley', 1, 1, 'Quiet Valley', 'Old Pilot');
        CREATE TABLE film_lookup (
            title_hint_norm TEXT NOT NULL, year_hint_key INTEGER NOT NULL,
            resolved_title TEXT NOT NULL, resolved_year INTEGER NOT NULL,
            PRIMARY KEY (title_hint_norm, year_hint_key)
        );
        INSERT INTO film_lookup VALUES ('harbour lights', 2011, 'Harbour Lights', 2011);
        """
    )
    conn.commit()
    conn.close()


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {name for (name,) in rows}


def test_a_previous_version_file_is_dropped_and_made_again(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    _make_version_1_file(db)

    cache = SqliteMetadataCache(db)
    assert (
        cache.get_search(provider="tmdb", mode=ScanMode.TV, hint="quiet valley", year=None) is None
    )
    cache.put_search(
        provider="tmdb", mode=ScanMode.TV, hint="quiet valley", year=None, results=_FOUND
    )
    cache.close()

    assert "tv_lookup" not in _tables(db)
    assert "film_lookup" not in _tables(db)
    reopened = SqliteMetadataCache(db)
    assert (
        reopened.get_search(provider="tmdb", mode=ScanMode.TV, hint="quiet valley", year=None)
        == _FOUND
    )
    reopened.close()


def test_the_reset_leaves_tables_the_cache_never_made(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    _make_version_1_file(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE notes (body TEXT)")
    conn.commit()
    conn.close()

    cache = SqliteMetadataCache(db)
    cache.get_episode(provider="tmdb", show_id="1", season=1, episode=1)
    cache.close()

    assert "notes" in _tables(db)
    assert "tv_lookup" not in _tables(db)


def test_a_corrupt_file_raises_cache_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.db"
    p.write_bytes(b"CORRUPT")
    cache = SqliteMetadataCache(p)
    with pytest.raises(CacheError):
        cache.get_episode(provider="tmdb", show_id="1", season=1, episode=1)


def test_an_unreadable_stored_entry_raises_cache_error(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    cache = SqliteMetadataCache(db)
    cache.put_search(provider="tmdb", mode=ScanMode.TV, hint="x", year=None, results=_FOUND)
    cache.close()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE search_lookup SET results = 'not json'")
    conn.commit()
    conn.close()

    reopened = SqliteMetadataCache(db)
    with pytest.raises(CacheError):
        reopened.get_search(provider="tmdb", mode=ScanMode.TV, hint="x", year=None)
    reopened.close()
