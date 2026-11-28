"""The per-build lookups over a Provider and the SQLite cache (a real file in tmp_path)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.core.models import Candidate
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.util.errors import CacheError, ProviderError

_VALLEY = Candidate(id="7001", name="Quiet Valley", year=2019, poster_ref="/quiet-valley.jpg")
_HARBOUR = Candidate(id="501", name="Harbour Lights", year=2011, poster_ref="/harbour.jpg")


class CountingTv:
    """A TV stand-in that answers from fixed data and counts its requests."""

    def __init__(
        self,
        shows: dict[str, tuple[Candidate, ...]],
        episodes: dict[tuple[str, int, int], str] | None = None,
    ) -> None:
        self.shows = shows
        self.episodes = episodes or {}
        self.searches: list[str] = []
        self.episode_requests: list[tuple[str, int, int]] = []
        self.fail = False

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.searches.append(hint)
        if self.fail:
            raise ProviderError("TMDB request failed with HTTP 503")
        return self.shows.get(hint.casefold(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        self.episode_requests.append((show_id, season, episode))
        return self.episodes.get((show_id, season, episode))


class CountingFilm:
    """A Film stand-in keyed by (hint, year) that counts its requests."""

    def __init__(self, films: dict[tuple[str, int | None], tuple[Candidate, ...]]) -> None:
        self.films = films
        self.searches: list[tuple[str, int | None]] = []

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append((hint, year))
        return self.films.get((hint.casefold(), year), ())


@pytest.fixture
def cache(tmp_path: Path) -> SqliteMetadataCache:
    c = SqliteMetadataCache(tmp_path / "cache.db")
    yield c
    c.close()


def test_a_build_searches_each_hint_once(cache: SqliteMetadataCache) -> None:
    tv = CountingTv({"quiet valley": (_VALLEY,)})
    build = TvLookup(tv, cache=cache, provider_id="tmdb")

    assert build.search_shows(hint="Quiet Valley") == (_VALLEY,)
    assert build.search_shows(hint="quiet valley ") == (_VALLEY,)
    assert tv.searches == ["Quiet Valley"]


def test_a_build_without_the_cache_searches_each_hint_once() -> None:
    tv = CountingTv({})
    build = TvLookup(tv)

    assert build.search_shows(hint="Nothing Here") == ()
    assert build.search_shows(hint="Nothing Here") == ()
    assert tv.searches == ["Nothing Here"]


def test_a_second_build_is_served_from_the_cache(cache: SqliteMetadataCache) -> None:
    tv = CountingTv({"quiet valley": (_VALLEY,)}, {("7001", 1, 2): "Thaw"})
    first = TvLookup(tv, cache=cache, provider_id="tmdb")
    first.search_shows(hint="Quiet Valley")
    first.episode_title(show_id="7001", season=1, episode=2)

    second = TvLookup(tv, cache=cache, provider_id="tmdb")
    assert second.search_shows(hint="Quiet Valley") == (_VALLEY,)
    assert second.episode_title(show_id="7001", season=1, episode=2) == "Thaw"
    assert len(tv.searches) == 1
    assert len(tv.episode_requests) == 1


def test_nothing_found_is_not_stored(cache: SqliteMetadataCache) -> None:
    tv = CountingTv({})
    TvLookup(tv, cache=cache, provider_id="tmdb").search_shows(hint="Nothing")
    TvLookup(tv, cache=cache, provider_id="tmdb").episode_title(show_id="1", season=1, episode=1)

    again = TvLookup(tv, cache=cache, provider_id="tmdb")
    again.search_shows(hint="Nothing")
    again.episode_title(show_id="1", season=1, episode=1)
    assert len(tv.searches) == 2
    assert len(tv.episode_requests) == 2


def test_an_entry_from_one_provider_is_never_returned_for_another(
    cache: SqliteMetadataCache,
) -> None:
    tmdb = CountingTv({"quiet valley": (_VALLEY,)}, {("7001", 1, 1): "Pilot"})
    TvLookup(tmdb, cache=cache, provider_id="tmdb").search_shows(hint="Quiet Valley")
    TvLookup(tmdb, cache=cache, provider_id="tmdb").episode_title(
        show_id="7001", season=1, episode=1
    )
    tvdb = CountingTv({})
    other = TvLookup(tvdb, cache=cache, provider_id="tvdb")
    assert other.search_shows(hint="Quiet Valley") == ()
    assert other.episode_title(show_id="7001", season=1, episode=1) is None
    assert tvdb.searches == ["Quiet Valley"]

    tmdb_films = CountingFilm({("harbour lights", 2011): (_HARBOUR,)})
    FilmLookup(tmdb_films, cache=cache, provider_id="tmdb").search_films(
        hint="Harbour Lights", year=2011
    )
    omdb = CountingFilm({})
    assert (
        FilmLookup(omdb, cache=cache, provider_id="omdb").search_films(
            hint="Harbour Lights", year=2011
        )
        == ()
    )
    assert omdb.searches == [("Harbour Lights", 2011), ("Harbour Lights", None)]


def test_one_providers_tv_and_film_entries_are_kept_apart(cache: SqliteMetadataCache) -> None:
    tv = CountingTv({"harbour lights": (_VALLEY,)})
    TvLookup(tv, cache=cache, provider_id="tmdb").search_shows(hint="Harbour Lights")

    films = CountingFilm({("harbour lights", None): (_HARBOUR,)})
    found = FilmLookup(films, cache=cache, provider_id="tmdb").search_films(
        hint="Harbour Lights", year=None
    )
    assert found == (_HARBOUR,)
    assert films.searches == [("Harbour Lights", None)]


def test_a_film_search_with_a_year_that_finds_nothing_is_tried_without_it(
    cache: SqliteMetadataCache,
) -> None:
    films = CountingFilm({("harbour lights", None): (_HARBOUR,)})
    first = FilmLookup(films, cache=cache, provider_id="omdb")

    assert first.search_films(hint="Harbour Lights", year=2026) == (_HARBOUR,)
    assert films.searches == [("Harbour Lights", 2026), ("Harbour Lights", None)]
    assert first.search_films(hint="Harbour Lights", year=2026) == (_HARBOUR,)
    assert len(films.searches) == 2

    second = FilmLookup(films, cache=cache, provider_id="omdb")
    assert second.search_films(hint="Harbour Lights", year=2026) == (_HARBOUR,)
    assert second.search_films(hint="Harbour Lights", year=None) == (_HARBOUR,)
    assert len(films.searches) == 2


def test_a_film_search_that_finds_nothing_either_way_is_not_stored(
    cache: SqliteMetadataCache,
) -> None:
    films = CountingFilm({})
    assert (
        FilmLookup(films, cache=cache, provider_id="omdb").search_films(hint="Z", year=2026) == ()
    )
    FilmLookup(films, cache=cache, provider_id="omdb").search_films(hint="Z", year=2026)
    assert films.searches == [("Z", 2026), ("Z", None), ("Z", 2026), ("Z", None)]


def test_a_film_search_without_a_year_is_not_retried() -> None:
    films = CountingFilm({})
    assert FilmLookup(films).search_films(hint="Z", year=None) == ()
    assert films.searches == [("Z", None)]


def test_a_failure_reaches_the_caller_and_is_not_stored(cache: SqliteMetadataCache) -> None:
    tv = CountingTv({"quiet valley": (_VALLEY,)})
    tv.fail = True
    build = TvLookup(tv, cache=cache, provider_id="tmdb")
    with pytest.raises(ProviderError, match="HTTP 503"):
        build.search_shows(hint="Quiet Valley")

    tv.fail = False
    assert build.search_shows(hint="Quiet Valley") == (_VALLEY,)


def test_a_failed_cache_read_falls_back_to_the_network_with_a_warning(
    cache: SqliteMetadataCache,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(**_: object) -> None:
        raise CacheError("SQLite read failed for search cache")

    monkeypatch.setattr(cache, "get_search", broken)
    monkeypatch.setattr(cache, "get_episode", broken)
    caplog.set_level(logging.WARNING)
    tv = CountingTv({"quiet valley": (_VALLEY,)}, {("7001", 1, 1): "Pilot"})
    build = TvLookup(tv, cache=cache, provider_id="tmdb")

    assert build.search_shows(hint="Quiet Valley") == (_VALLEY,)
    assert build.episode_title(show_id="7001", season=1, episode=1) == "Pilot"
    films = FilmLookup(CountingFilm({("x", None): (_HARBOUR,)}), cache=cache, provider_id="tmdb")
    assert films.search_films(hint="x", year=None) == (_HARBOUR,)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    assert all("cache read failed" in r.getMessage() for r in warnings)


def test_a_failed_cache_write_still_returns_the_answer_with_a_warning(
    cache: SqliteMetadataCache,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(**_: object) -> None:
        raise CacheError("SQLite write failed")

    monkeypatch.setattr(cache, "put_search", broken)
    monkeypatch.setattr(cache, "put_episode", broken)
    caplog.set_level(logging.WARNING)
    tv = CountingTv({"quiet valley": (_VALLEY,)}, {("7001", 1, 1): "Pilot"})
    build = TvLookup(tv, cache=cache, provider_id="tmdb")

    assert build.search_shows(hint="Quiet Valley") == (_VALLEY,)
    assert build.episode_title(show_id="7001", season=1, episode=1) == "Pilot"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("cache write failed" in r.getMessage() for r in warnings)


def test_a_corrupt_cache_file_falls_back_to_the_network(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = tmp_path / "bad.db"
    db.write_bytes(b"CORRUPT")
    caplog.set_level(logging.WARNING)
    tv = CountingTv({"quiet valley": (_VALLEY,)})
    broken_cache = SqliteMetadataCache(db)

    found = TvLookup(tv, cache=broken_cache, provider_id="tmdb").search_shows(hint="Quiet Valley")

    assert found == (_VALLEY,)
    assert "cache" in caplog.text.lower()
    broken_cache.close()


def test_a_build_on_another_thread_reads_what_the_first_stored(
    cache: SqliteMetadataCache, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    tv = CountingTv({"quiet valley": (_VALLEY,)}, {("7001", 1, 1): "Pilot"})
    results: list[object] = []

    def build() -> None:
        lookup = TvLookup(tv, cache=cache, provider_id="tmdb")
        results.append(lookup.search_shows(hint="Quiet Valley"))
        results.append(lookup.episode_title(show_id="7001", season=1, episode=1))

    for _ in range(2):
        worker = threading.Thread(target=build)
        worker.start()
        worker.join()

    assert results == [(_VALLEY,), "Pilot", (_VALLEY,), "Pilot"]
    assert len(tv.searches) == 1
    assert len(tv.episode_requests) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_build_scoped_provider_gets_one_view_per_build() -> None:
    class Scoped(CountingTv):
        def __init__(self) -> None:
            super().__init__({"quiet valley": (_VALLEY,)})
            self.builds = 0

        def for_build(self) -> CountingTv:
            self.builds += 1
            return self

    tv = Scoped()
    lookup = TvLookup(tv)
    lookup.search_shows(hint="Quiet Valley")
    lookup.episode_title(show_id="7001", season=1, episode=1)
    assert tv.builds == 1
    TvLookup(tv)
    assert tv.builds == 2


def test_a_cache_needs_a_provider_id(cache: SqliteMetadataCache) -> None:
    with pytest.raises(ValueError, match="provider_id"):
        TvLookup(CountingTv({}), cache=cache)
    with pytest.raises(ValueError, match="provider_id"):
        FilmLookup(CountingFilm({}), cache=cache)
