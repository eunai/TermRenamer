"""What building a Plan reports to its progress listener while it runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from termrenamer.core.models import Candidate, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.core.progress import PlanEvent, TitleLookedUp


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

    assert heard == [
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
