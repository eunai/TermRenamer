"""What building a Plan reports to its progress listener while it runs."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from termrenamer.api.lookup import TvLookup
from termrenamer.core.models import Candidate, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.core.progress import (
    BuildFinished,
    FileLookedUp,
    PlanEvent,
    Scanned,
    ScannedTitle,
    TitleLookedUp,
    TitleLookupStarted,
)
from termrenamer.persistence.cache import SqliteMetadataCache


@dataclass
class FilmStandIn:
    """Answers film searches from fixed data, keyed by (normalised hint, year)."""

    films: dict[tuple[str, int | None], tuple[Candidate, ...]]
    searches: list[str] = field(default_factory=list)

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append(hint)
        return self.films.get((hint.casefold().strip(), year), ())


def _film_options() -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.FILM,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=False,
        season_folders=False,
    )


METROPOLIS = Candidate(id="19", name="Metropolis", year=1927, poster_ref="/m.jpg")
THE_KID = Candidate(id="10098", name="The Kid", year=1921)


def _films() -> FilmStandIn:
    return FilmStandIn(
        films={("metropolis", 1927): (METROPOLIS,), ("the kid", 1921): (THE_KID,)},
    )


def _backups(folder: Path) -> Path:
    for name in ("Metropolis 1927.mkv", "The Kid 1921.mkv", "Phantom 1925.mkv", "notes.txt"):
        (folder / name).write_bytes(b"x")
    return folder


def test_each_title_is_reported_once_found_or_not_in_the_order_its_search_finishes(
    tmp_path: Path,
) -> None:
    heard: list[PlanEvent] = []
    provider = _films()

    plan_queue([_backups(tmp_path)], _film_options(), provider, listener=heard.append)

    assert [e for e in heard if isinstance(e, TitleLookedUp)] == [
        TitleLookedUp(name="Metropolis", year=1927, match=METROPOLIS),
        TitleLookedUp(name="Phantom", year=1925, match=None),
        TitleLookedUp(name="The Kid", year=1921, match=THE_KID),
    ]
    # One event per Title's search, in the order the searches ran (a year retry included).
    assert [e.name for e in heard if isinstance(e, TitleLookedUp)] == list(
        dict.fromkeys(provider.searches)
    )


def test_a_listener_that_raises_stops_the_build_and_leaves_no_plan(tmp_path: Path) -> None:
    class Boom(Exception):
        pass

    def listener(event: PlanEvent) -> None:
        raise Boom

    with pytest.raises(Boom):
        plan_queue([_backups(tmp_path)], _film_options(), _films(), listener=listener)

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Metropolis 1927.mkv",
        "Phantom 1925.mkv",
        "The Kid 1921.mkv",
        "notes.txt",
    ]


def test_a_build_with_no_listener_reports_nothing_and_plans_the_same(tmp_path: Path) -> None:
    heard: list[PlanEvent] = []
    folder = _backups(tmp_path)

    with_listener = plan_queue([folder], _film_options(), _films(), listener=heard.append)
    without = plan_queue([folder], _film_options(), _films())

    assert with_listener.plan == without.plan


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data."""

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return self.episodes.get((show_id, season, episode))


SHOW = Candidate(id="11", name="Harbour Lights", year=2019)
FERRY = Candidate(id="12", name="Night Ferry", year=2021)


def _tv_options() -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=False,
        season_folders=False,
    )


def _tv() -> TvStandIn:
    # Harbour Lights S01E02 is not in the Provider's episode list.
    return TvStandIn(
        shows={"harbour lights": (SHOW,), "night ferry": (FERRY,)},
        episodes={("11", 1, 1): "The Tide Comes In", ("12", 1, 1): "Cast Off"},
    )


def _tv_backups(folder: Path) -> Path:
    for name in (
        "Harbour Lights S01E01.mkv",
        "Harbour Lights S01E01.srt",
        "Harbour Lights S01E02.mkv",
        "Lost Signal S01E01.mkv",
        "Night Ferry S01E01.mkv",
        "holiday.mkv",
        "notes.txt",
    ):
        (folder / name).write_bytes(b"x")
    return folder


def test_the_listener_hears_the_scan_each_lookup_and_the_end_in_order(tmp_path: Path) -> None:
    heard: list[PlanEvent] = []
    folder = _tv_backups(tmp_path).resolve()

    plan_queue([folder], _tv_options(), _tv(), listener=heard.append)

    assert heard == [
        Scanned(
            files=4,
            titles=(
                ScannedTitle(name="Harbour Lights", year=None, videos=2),
                ScannedTitle(name="Lost Signal", year=None, videos=1),
                ScannedTitle(name="Night Ferry", year=None, videos=1),
            ),
            not_recognised=(folder / "holiday.mkv",),
        ),
        TitleLookupStarted(name="Harbour Lights", year=None),
        TitleLookedUp(name="Harbour Lights", year=None, match=SHOW),
        FileLookedUp(path=folder / "Harbour Lights S01E01.mkv", matched=True),
        FileLookedUp(path=folder / "Harbour Lights S01E02.mkv", matched=False),
        TitleLookupStarted(name="Lost Signal", year=None),
        TitleLookedUp(name="Lost Signal", year=None, match=None),
        FileLookedUp(path=folder / "Lost Signal S01E01.mkv", matched=False),
        TitleLookupStarted(name="Night Ferry", year=None),
        TitleLookedUp(name="Night Ferry", year=None, match=FERRY),
        FileLookedUp(path=folder / "Night Ferry S01E01.mkv", matched=True),
        BuildFinished(),
    ]


def test_the_total_is_reported_before_the_first_lookup(tmp_path: Path) -> None:
    heard: list[PlanEvent] = []
    heard_at_first_search: list[PlanEvent] = []

    class Watching(TvStandIn):
        def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
            if not heard_at_first_search:
                heard_at_first_search.extend(heard)
            return super().search_shows(hint=hint)

    stand_in = _tv()
    watching = Watching(shows=stand_in.shows, episodes=stand_in.episodes)

    plan_queue([_tv_backups(tmp_path)], _tv_options(), watching, listener=heard.append)

    [scanned] = [e for e in heard if isinstance(e, Scanned)]
    assert heard_at_first_search[0] == scanned
    assert scanned.files == 4
    assert scanned.files == len([e for e in heard if isinstance(e, FileLookedUp)])


def test_a_cached_answer_is_reported_the_same_way_as_a_network_one(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    _tv_backups(folder)
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    try:
        first: list[PlanEvent] = []
        second: list[PlanEvent] = []
        network = _tv()
        plan_queue(
            [folder],
            _tv_options(),
            TvLookup(network, cache=cache, provider_id="tmdb"),
            listener=first.append,
        )
        offline = TvStandIn(shows={}, episodes={})
        plan_queue(
            [folder],
            _tv_options(),
            TvLookup(offline, cache=cache, provider_id="tmdb"),
            listener=second.append,
        )
    finally:
        cache.close()

    # The second build's found answers all came from the cache; the stand-in it would
    # ask knows nothing. "Nothing found" is never cached, so Lost Signal is asked again.
    assert second == first


class _CancelOn:
    """A stand-in Provider that sets the cancel signal during its ``n``-th search."""

    def __init__(self, n: int) -> None:
        self.cancel = threading.Event()
        self.searches: list[str] = []
        self._n = n
        self._inner = _tv()

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.searches.append(hint)
        if len(self.searches) == self._n:
            self.cancel.set()
        return self._inner.search_shows(hint=hint)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return self._inner.episode_title(show_id=show_id, season=season, episode=episode)


def test_a_build_cancelled_mid_way_makes_no_more_lookups_and_returns_no_plan(
    tmp_path: Path,
) -> None:
    heard: list[PlanEvent] = []
    stand_in = _CancelOn(2)
    folder = _tv_backups(tmp_path)
    before = sorted(p.name for p in folder.iterdir())

    build = plan_queue(
        [folder], _tv_options(), stand_in, listener=heard.append, cancel=stand_in.cancel
    )

    assert build is None
    # The lookup under way when the signal was set finished; no other started.
    assert stand_in.searches == ["Harbour Lights", "Lost Signal"]
    assert [type(e) for e in heard[-2:]] == [TitleLookedUp, FileLookedUp]
    assert not any(isinstance(e, BuildFinished) for e in heard)
    assert sorted(p.name for p in folder.iterdir()) == before


def test_the_cancel_signal_is_checked_before_each_episode_lookup(tmp_path: Path) -> None:
    stand_in = _CancelOn(1)
    episodes: list[tuple[str, int, int]] = []
    inner = stand_in._inner

    def episode_title(*, show_id: str, season: int, episode: int) -> str | None:
        episodes.append((show_id, season, episode))
        return inner.episode_title(show_id=show_id, season=season, episode=episode)

    stand_in.episode_title = episode_title  # type: ignore[method-assign]

    build = plan_queue([_tv_backups(tmp_path)], _tv_options(), stand_in, cancel=stand_in.cancel)

    assert build is None
    assert episodes == []


def test_a_signal_never_set_plans_the_same_as_no_signal(tmp_path: Path) -> None:
    folder = _tv_backups(tmp_path)

    with_signal = plan_queue([folder], _tv_options(), _tv(), cancel=threading.Event())
    without = plan_queue([folder], _tv_options(), _tv())

    assert with_signal is not None
    assert with_signal.plan == without.plan
