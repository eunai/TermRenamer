"""Pick a different Match for a Title: the change derives a new Plan from the old one.

Real temporary folders and stand-in Providers, through :func:`plan_queue`,
:func:`look_up_episodes`, :func:`search_typed` and :func:`derive_plan`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.core.models import Candidate, EntryStatus, Plan, PlanOptions, ScanMode, Title
from termrenamer.core.planning import (
    LeaveOut,
    PickMatch,
    PutBack,
    derive_plan,
    look_up_episodes,
    plan_queue,
    search_typed,
    typed_hint,
)
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.persistence.cache import SqliteMetadataCache

HEAT = Candidate(id="949", name="Heat", year=1995, poster_ref="/heat.jpg")
HEAT_1986 = Candidate(id="31", name="Heat", year=1986)
HEAT_WAVE = Candidate(id="77", name="Heat Wave", year=1990)


@dataclass
class FilmStandIn:
    """Answers film searches from fixed data, keyed by (normalised hint, year), and
    records each search."""

    films: dict[tuple[str, int | None], tuple[Candidate, ...]]
    searches: list[tuple[str, int | None]] = field(default_factory=list)

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append((hint, year))
        return self.films.get((hint.casefold().strip(), year), ())


HARBOUR = Candidate(id="11", name="Harbour Lights", year=2019)
HARBOUR_US = Candidate(id="40", name="Harbour Lights (US)", year=2022)
FERRY = Candidate(id="12", name="Night Ferry", year=2021)
US_PILOT = "Harbour Lights (US) - S01E01 - Pilot"


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data, and records each lookup."""

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]
    lookups: list[str] = field(default_factory=list)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.lookups.append(hint)
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        self.lookups.append(f"{show_id} {season} {episode}")
        return self.episodes.get((show_id, season, episode))


def _harbour() -> TvStandIn:
    """Harbour Lights has two episodes; the US show of that name has only the first."""
    return TvStandIn(
        shows={
            "harbour lights": (HARBOUR, HARBOUR_US),
            "night ferry": (FERRY,),
        },
        episodes={
            ("11", 1, 1): "The Tide Comes In",
            ("11", 1, 2): "Salt and Rope",
            ("40", 1, 1): "Pilot",
            ("12", 1, 1): "Cast Off",
        },
    )


def _tv_options(*, library: Path | None = None) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=library,
        folder_rename=library is not None,
        season_folders=False,
        name_taken=NameTakenPolicy.SUFFIX,
    )


def _harbour_folder(tmp_path: Path) -> Path:
    tmp_path.mkdir(exist_ok=True)
    for name in (
        "Harbour.Lights.S01E01.mkv",
        "Harbour.Lights.S01E01.srt",
        "Harbour.Lights.S01E02.mkv",
    ):
        (tmp_path / name).write_bytes(b"x")
    return tmp_path


def _heat() -> FilmStandIn:
    return FilmStandIn(films={("heat", 1995): (HEAT, HEAT_1986, HEAT_WAVE)})


def _film_options(*, library: Path | None = None) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.FILM,
        provider_id="tmdb",
        destination_root=library,
        folder_rename=library is not None,
        season_folders=False,
        name_taken=NameTakenPolicy.SUFFIX,
    )


def _summary(plan: Plan) -> list[tuple[str, str | None, EntryStatus]]:
    return [
        (
            e.source.name,
            e.destination.name if e.destination is not None else None,
            e.status,
        )
        for e in plan.entries
    ]


def _title(plan: Plan, name: str) -> Title:
    return next(t for t in plan.titles if t.name == name)


def test_a_film_title_takes_the_picked_candidates_title_and_year_with_no_lookup(
    tmp_path: Path,
) -> None:
    (tmp_path / "Heat.1995.mkv").write_bytes(b"h")
    (tmp_path / "Heat.1995.srt").write_text("s", encoding="utf-8")
    provider = _heat()
    plan = plan_queue([tmp_path], _film_options(), provider).plan
    searches = list(provider.searches)
    [title] = plan.titles
    assert title.match == HEAT
    assert title.candidates == (HEAT_1986, HEAT_WAVE)

    derived = derive_plan(plan, PickMatch(title, HEAT_1986, found=(HEAT, HEAT_1986, HEAT_WAVE)))

    assert _summary(derived) == [
        ("Heat.1995.mkv", "Heat (1986).mkv", EntryStatus.READY),
        ("Heat.1995.srt", "Heat (1986).srt", EntryStatus.READY),
    ]
    [picked] = derived.titles
    assert (picked.name, picked.year, picked.match) == ("Heat", 1986, HEAT_1986)
    # The picker can offer the first Match again: it is a Candidate now.
    assert picked.candidates == (HEAT, HEAT_WAVE)
    assert all(e.title == picked for e in derived.entries)
    assert provider.searches == searches
    # The Plan never changes: the pick made a new one.
    assert plan.titles == (title,)


def test_a_tv_title_takes_episode_titles_looked_up_from_the_picked_show(tmp_path: Path) -> None:
    provider = _harbour()
    plan = plan_queue([_harbour_folder(tmp_path)], _tv_options(), provider).plan
    [title] = plan.titles
    provider.lookups.clear()

    episodes = look_up_episodes(plan, title, HARBOUR_US, provider)

    assert provider.lookups == ["40 1 1", "40 1 2"]
    assert episodes is not None
    provider.lookups.clear()
    derived = derive_plan(
        plan, PickMatch(title, HARBOUR_US, found=(HARBOUR, HARBOUR_US), episodes=episodes)
    )

    assert provider.lookups == []
    assert _summary(derived) == [
        (
            "Harbour.Lights.S01E01.mkv",
            f"{US_PILOT}.mkv",
            EntryStatus.READY,
        ),
        (
            "Harbour.Lights.S01E01.srt",
            f"{US_PILOT}.srt",
            EntryStatus.READY,
        ),
        # The picked show has no second episode: that one file has no match.
        ("Harbour.Lights.S01E02.mkv", None, EntryStatus.NO_MATCH),
    ]
    [picked] = derived.titles
    assert (picked.match, picked.candidates, picked.seasons) == (HARBOUR_US, (HARBOUR,), (1,))


def test_looking_up_episodes_stops_when_cancelled(tmp_path: Path) -> None:
    provider = _harbour()
    plan = plan_queue([_harbour_folder(tmp_path)], _tv_options(), provider).plan
    provider.lookups.clear()
    cancel = threading.Event()
    cancel.set()

    assert look_up_episodes(plan, plan.titles[0], HARBOUR_US, provider, cancel=cancel) is None
    assert provider.lookups == []


def test_a_left_out_video_stays_left_out_and_comes_back_with_the_picked_name(
    tmp_path: Path,
) -> None:
    provider = _harbour()
    plan = plan_queue([_harbour_folder(tmp_path)], _tv_options(), provider).plan
    first = next(v for v in plan.videos if v.episode == 1)
    plan = derive_plan(plan, LeaveOut(first))
    [title] = plan.titles
    episodes = look_up_episodes(plan, title, HARBOUR_US, provider)
    assert episodes is not None

    derived = derive_plan(plan, PickMatch(title, HARBOUR_US, episodes=episodes))
    assert derived.videos[0].status is EntryStatus.LEFT_OUT
    put_back = derive_plan(derived, PutBack(derived.videos[0]))

    assert _summary(put_back)[:2] == [
        (
            "Harbour.Lights.S01E01.mkv",
            f"{US_PILOT}.mkv",
            EntryStatus.READY,
        ),
        (
            "Harbour.Lights.S01E01.srt",
            f"{US_PILOT}.srt",
            EntryStatus.READY,
        ),
    ]


def test_a_left_out_video_the_picked_show_lacks_comes_back_with_no_match(tmp_path: Path) -> None:
    provider = _harbour()
    plan = plan_queue([_harbour_folder(tmp_path)], _tv_options(), provider).plan
    second = next(v for v in plan.videos if v.episode == 2)
    plan = derive_plan(plan, LeaveOut(second))
    [title] = plan.titles
    episodes = look_up_episodes(plan, title, HARBOUR_US, provider)
    assert episodes is not None
    derived = derive_plan(plan, PickMatch(title, HARBOUR_US, episodes=episodes))

    put_back = derive_plan(derived, PutBack(derived.videos[1]))

    assert _summary(put_back)[2] == ("Harbour.Lights.S01E02.mkv", None, EntryStatus.NO_MATCH)


def test_a_tv_pick_without_the_episode_titles_is_refused(tmp_path: Path) -> None:
    plan = plan_queue([_harbour_folder(tmp_path)], _tv_options(), _harbour()).plan

    with pytest.raises(ValueError, match="No episode title was looked up"):
        derive_plan(plan, PickMatch(plan.titles[0], HARBOUR_US))


def _two_heats(tmp_path: Path) -> FilmStandIn:
    """Heat (1995) and Heat (1986), each found first by its own year."""
    (tmp_path / "Heat.1986.mkv").write_bytes(b"86")
    (tmp_path / "Heat.1995.mkv").write_bytes(b"95")
    return FilmStandIn(
        films={
            ("heat", 1995): (HEAT, HEAT_1986, HEAT_WAVE),
            ("heat", 1986): (HEAT_1986, HEAT),
        }
    )


def test_two_titles_that_share_the_picked_match_become_one_and_names_are_claimed_again(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue([tmp_path], _film_options(library=library), _two_heats(tmp_path)).plan
    older = _title(plan, "Heat")
    assert older.match == HEAT_1986

    derived = derive_plan(plan, PickMatch(older, HEAT, found=(HEAT_1986, HEAT)))

    [merged] = derived.titles
    assert merged.match == HEAT
    # The picked group's title hint ("heat", 1986) sorts first: its Candidates stay.
    assert merged.candidates == (HEAT_1986,)
    assert _summary(derived) == [
        ("Heat.1986.mkv", "Heat (1995).mkv", EntryStatus.READY),
        ("Heat.1995.mkv", "Heat (1995) (1).mkv", EntryStatus.NAME_TAKEN),
    ]
    assert all(e.title == merged for e in derived.entries)


def test_a_merged_title_keeps_the_candidates_of_the_group_whose_hint_sorts_first(
    tmp_path: Path,
) -> None:
    plan = plan_queue([tmp_path], _film_options(), _two_heats(tmp_path)).plan
    newer = next(t for t in plan.titles if t.match == HEAT)

    derived = derive_plan(plan, PickMatch(newer, HEAT_1986, found=(HEAT, HEAT_1986, HEAT_WAVE)))

    [merged] = derived.titles
    # The other Title's group ("heat", 1986) sorts before the picked one's.
    assert (merged.match, merged.candidates) == (HEAT_1986, (HEAT,))


def _not_recognised(tmp_path: Path) -> Path:
    """A film whose name the parser cannot read, with its subtitle, beside Heat."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "1080p.mkv").write_bytes(b"?")
    (tmp_path / "1080p.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Heat.1995.mkv").write_bytes(b"h")
    return tmp_path


def test_a_not_recognised_film_given_a_match_forms_a_title_with_its_sidecars(
    tmp_path: Path,
) -> None:
    plan = plan_queue([_not_recognised(tmp_path)], _film_options(), _heat()).plan
    video = plan.entries[0]
    assert video.status is EntryStatus.NOT_RECOGNISED
    assert plan.entries[1].status is EntryStatus.NOT_RECOGNISED

    derived = derive_plan(plan, PickMatch(video, HEAT_WAVE, found=(HEAT_WAVE, HEAT)))

    assert _summary(derived) == [
        ("1080p.mkv", "Heat Wave (1990).mkv", EntryStatus.READY),
        ("1080p.srt", "Heat Wave (1990).srt", EntryStatus.READY),
        ("Heat.1995.mkv", "Heat (1995).mkv", EntryStatus.READY),
    ]
    wave = _title(derived, "Heat Wave")
    assert (wave.match, wave.candidates) == (HEAT_WAVE, (HEAT,))
    assert [t.name for t in derived.titles] == ["Heat", "Heat Wave"]
    assert derived.entries[0].title == wave and derived.entries[1].title == wave
    # It keeps its place in source-path order.
    assert [e.source for e in derived.entries] == [e.source for e in plan.entries]


def test_a_not_recognised_film_joins_the_title_that_has_its_match(tmp_path: Path) -> None:
    plan = plan_queue([_not_recognised(tmp_path)], _film_options(), _heat()).plan
    [heat] = plan.titles

    derived = derive_plan(plan, PickMatch(plan.entries[0], HEAT, found=(HEAT,)))

    [joined] = derived.titles
    assert (joined.match, joined.candidates) == (HEAT, heat.candidates)
    assert _summary(derived) == [
        ("1080p.mkv", "Heat (1995).mkv", EntryStatus.READY),
        ("1080p.srt", "Heat (1995).srt", EntryStatus.READY),
        ("Heat.1995.mkv", "Heat (1995) (1).mkv", EntryStatus.NAME_TAKEN),
    ]


def test_a_not_recognised_tv_file_cannot_be_given_a_match(tmp_path: Path) -> None:
    (tmp_path / "holiday.mkv").write_bytes(b"?")
    plan = plan_queue([tmp_path], _tv_options(), _harbour()).plan
    [video] = plan.entries

    with pytest.raises(ValueError, match="not available yet"):
        derive_plan(plan, PickMatch(video, HARBOUR, episodes={video.source: "Pilot"}))


@pytest.mark.parametrize(
    ("text", "hint"),
    [
        ("Heat 1995", ("Heat", 1995)),
        ("  Heat (1995) ", ("Heat", 1995)),
        ("The Thing", ("The Thing", None)),
        ("1917", ("1917", None)),
        ("Blade Runner 2049", ("Blade Runner", 2049)),
        ("Heat1995", ("Heat1995", None)),
    ],
)
def test_a_four_digit_year_at_the_end_of_typed_text_is_the_year_hint(
    text: str, hint: tuple[str, int | None]
) -> None:
    assert typed_hint(text) == hint


def test_a_typed_film_search_asks_with_the_year_and_then_without_it() -> None:
    provider = FilmStandIn(films={("heat", None): (HEAT_WAVE, HEAT)})

    assert search_typed("Heat 1972", ScanMode.FILM, provider) == (HEAT_WAVE, HEAT)
    assert provider.searches == [("Heat", 1972), ("Heat", None)]


def test_a_typed_film_search_drops_a_result_without_a_year() -> None:
    no_year = Candidate(id="5", name="Heat", year=None)
    provider = FilmStandIn(films={("heat", None): (no_year, HEAT)})

    assert search_typed("heat", ScanMode.FILM, provider) == (HEAT,)


def test_a_typed_tv_search_keeps_the_shows_first_aired_in_the_year_hint() -> None:
    provider = _harbour()

    assert search_typed("Harbour Lights 2022", ScanMode.TV, provider) == (HARBOUR_US,)
    assert search_typed("Harbour Lights", ScanMode.TV, provider) == (HARBOUR, HARBOUR_US)
    # No show of that year: every show found is offered.
    assert search_typed("Harbour Lights 1990", ScanMode.TV, provider) == (HARBOUR, HARBOUR_US)
    # The year is not part of the hint the Provider is asked.
    assert provider.lookups == ["Harbour Lights"] * 3


def test_a_typed_search_that_finds_nothing_is_empty() -> None:
    assert search_typed("Nothing Like It", ScanMode.TV, _harbour()) == ()


@dataclass
class EchoFilms:
    """A Film Provider that answers any search with a film named as the text asked."""

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        return (Candidate(id="1", name=hint, year=year or 2000),)


UNTRUSTED = ["../../Outside", "..", "a/b\\c", "/etc/passwd", "C:\\Windows", " . "]


@pytest.mark.parametrize("name", UNTRUSTED)
def test_a_typed_title_cannot_place_a_film_outside_the_destination_root(
    tmp_path: Path, name: str
) -> None:
    library = tmp_path / "Library"
    queued = [_not_recognised(tmp_path / "in")]
    plan = plan_queue(queued, _film_options(library=library), _heat()).plan
    [found] = search_typed(f"{name} 1999", ScanMode.FILM, EchoFilms())

    derived = derive_plan(plan, PickMatch(plan.entries[0], found, found=(found,)))

    for entry in derived.entries:
        assert entry.destination is not None
        assert ".." not in entry.destination.parts
        assert entry.destination.parent.parent == library


@pytest.mark.parametrize("name", UNTRUSTED)
def test_names_from_the_provider_cannot_place_an_episode_outside_the_destination_root(
    tmp_path: Path, name: str
) -> None:
    library = tmp_path / "Library"
    source = _harbour_folder(tmp_path / "in")
    options = replace(_tv_options(library=library), season_folders=True)
    plan = plan_queue([source], options, _harbour()).plan
    [title] = plan.titles
    show = Candidate(id="66", name=name, year=None)
    episodes = {v.source: name for v in plan.videos}

    derived = derive_plan(plan, PickMatch(title, show, found=(show,), episodes=episodes))

    for entry in derived.entries:
        assert entry.destination is not None
        assert ".." not in entry.destination.parts
        # Library / show / Season 01 / file
        assert entry.destination.parent.parent.parent == library


def test_picking_never_resolves_a_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Library"
    provider = _harbour()
    (tmp_path / "Harbour.Lights.S01E01.mkv").write_bytes(b"1")
    (tmp_path / "Harbour.Lights.S01E01.srt").write_bytes(b"s")
    (tmp_path / "Night.Ferry.S01E01.mkv").write_bytes(b"2")
    plan = plan_queue([tmp_path], _tv_options(library=library), provider).plan
    ferry = _title(plan, "Night Ferry")

    def no_resolve(self: Path, strict: bool = False) -> Path:
        raise AssertionError(f"resolved {self} while deriving")

    monkeypatch.setattr(Path, "resolve", no_resolve)
    episodes = look_up_episodes(plan, ferry, HARBOUR, provider)
    assert episodes is not None
    derived = derive_plan(plan, PickMatch(ferry, HARBOUR, found=(HARBOUR,), episodes=episodes))
    monkeypatch.undo()

    # Night Ferry's file joins Harbour Lights, in the order the build recorded.
    assert [t.name for t in derived.titles] == ["Harbour Lights"]
    assert [e.source for e in derived.entries] == [e.source for e in plan.entries]
    assert _summary(derived)[2] == (
        "Night.Ferry.S01E01.mkv",
        "Harbour Lights - S01E01 - The Tide Comes In (1).mkv",
        EntryStatus.NAME_TAKEN,
    )


def test_a_picked_match_is_never_cached_as_the_answer_for_the_title_hint(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    (source / "Heat.1995.mkv").write_bytes(b"h")
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    provider = _heat()

    def lookup() -> FilmLookup:
        return FilmLookup(provider, cache=cache, provider_id="tmdb")

    provider.films[("heat wave", 1990)] = (HEAT_WAVE,)
    plan = plan_queue([source], _film_options(), lookup()).plan
    found = search_typed("Heat Wave 1990", ScanMode.FILM, lookup())
    derive_plan(plan, PickMatch(plan.titles[0], HEAT_1986, found=(HEAT, HEAT_1986)))
    derive_plan(plan, PickMatch(plan.titles[0], found[0], found=found))
    provider.searches.clear()

    again = plan_queue([source], _film_options(), lookup()).plan

    assert provider.searches == []  # the build was answered by the cache
    assert again.titles[0].match == HEAT
    assert cache.get_search(provider="tmdb", mode=ScanMode.FILM, hint="heat", year=1995) == (
        HEAT,
        HEAT_1986,
        HEAT_WAVE,
    )
    # The typed search is an ordinary search, cached under its own hint.
    assert cache.get_search(provider="tmdb", mode=ScanMode.FILM, hint="Heat Wave", year=1990) == (
        HEAT_WAVE,
    )
    cache.close()


def test_episodes_looked_up_for_a_pick_are_cached_by_show_not_by_title_hint(
    tmp_path: Path,
) -> None:
    cache = SqliteMetadataCache(tmp_path / "cache.db")
    provider = _harbour()
    source = _harbour_folder(tmp_path / "in")
    plan = plan_queue([source], _tv_options(), TvLookup(provider, cache=cache, provider_id="tmdb"))
    [title] = plan.plan.titles
    look_up_episodes(
        plan.plan, title, HARBOUR_US, TvLookup(provider, cache=cache, provider_id="tmdb")
    )

    again = plan_queue(
        [source], _tv_options(), TvLookup(provider, cache=cache, provider_id="tmdb")
    ).plan

    assert again.titles[0].match == HARBOUR
    assert cache.get_episode(provider="tmdb", show_id="40", season=1, episode=1) == "Pilot"
    cache.close()
