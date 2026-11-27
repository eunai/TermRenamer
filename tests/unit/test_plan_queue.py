"""Plan the queued Sources: the core entry point, on temporary folders with stand-in Providers."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from termrenamer.core.models import Candidate, EntryStatus, Plan, PlanEntry, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue
from termrenamer.util.errors import ProviderError


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data, and counts the calls."""

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]
    searches: list[str] = field(default_factory=list)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.searches.append(hint)
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        return self.episodes.get((show_id, season, episode))


def _tv_options(**kwargs: object) -> PlanOptions:
    values: dict[str, object] = {
        "mode": ScanMode.TV,
        "provider_id": "tmdb",
        "destination_root": None,
        "folder_rename": False,
        "season_folders": False,
    }
    values.update(kwargs)
    return PlanOptions(**values)  # type: ignore[arg-type]


def _show_name() -> TvStandIn:
    return TvStandIn(
        shows={
            "show name": (
                Candidate(id="1", name="Show Name", year=2010, poster_ref="/p1.jpg"),
                Candidate(id="2", name="Show Name (2020)", year=2020),
            ),
        },
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )


def test_a_folder_source_plans_each_video_under_its_title(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")

    plan = plan_queue([tmp_path], _tv_options(), _show_name()).plan

    assert plan.options == _tv_options()
    [entry] = plan.entries
    assert entry.source == (tmp_path / "Show.Name.S01E01.mkv").resolve()
    assert entry.destination == tmp_path.resolve() / "Show Name - S01E01 - Pilot.mkv"
    assert entry.status is EntryStatus.READY
    assert (entry.season, entry.episode) == (1, 1)
    [title] = plan.titles
    assert entry.title == title
    assert title.name == "Show Name"
    assert title.match == Candidate(id="1", name="Show Name", year=2010, poster_ref="/p1.jpg")
    assert title.candidates == (Candidate(id="2", name="Show Name (2020)", year=2020),)
    assert title.poster_ref == "/p1.jpg"
    assert title.seasons == (1,)


def _by_name(plan: Plan) -> dict[str, PlanEntry]:
    return {e.source.name: e for e in plan.entries}


def test_a_file_source_contributes_that_video_and_its_sidecars_only(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "show.name.s01e01.NFO").write_text("n", encoding="utf-8")
    (tmp_path / "Show.Name.S01E02.mkv").write_bytes(b"b")
    (tmp_path / "Show.Name.S01E02.srt").write_text("t", encoding="utf-8")

    plan = plan_queue([tmp_path / "Show.Name.S01E01.mkv"], _tv_options(), _show_name()).plan

    entries = _by_name(plan)
    assert sorted(entries) == [
        "Show.Name.S01E01.mkv",
        "Show.Name.S01E01.srt",
        "show.name.s01e01.NFO",
    ]
    video = entries["Show.Name.S01E01.mkv"]
    for sidecar_name, suffix in (
        ("Show.Name.S01E01.srt", ".srt"),
        ("show.name.s01e01.NFO", ".nfo"),
    ):
        sidecar = entries[sidecar_name]
        assert sidecar.video == video.source
        assert sidecar.is_sidecar
        assert sidecar.status is EntryStatus.READY
        assert sidecar.title == video.title
        assert sidecar.destination == tmp_path.resolve() / f"Show Name - S01E01 - Pilot{suffix}"
    assert [e.source.name for e in plan.entries] == sorted(
        entries, key=lambda name: str(tmp_path.resolve() / name).casefold()
    )


def test_overlapping_sources_plan_each_file_once_under_the_outermost_folder(
    tmp_path: Path,
) -> None:
    outer = tmp_path / "Backups"
    inner = outer / "Show Name" / "Disc 1"
    inner.mkdir(parents=True)
    video = inner / "Show.Name.S01E01.mkv"
    video.write_bytes(b"a")
    (inner / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    options = _tv_options(folder_rename=True, season_folders=True)

    for queue in ([video, inner, outer], [inner, outer, video], [outer, video]):
        plan = plan_queue(queue, options, _show_name()).plan

        assert sorted(e.source.name for e in plan.entries) == [
            "Show.Name.S01E01.mkv",
            "Show.Name.S01E01.srt",
        ]
        expected = outer.resolve() / "Show Name" / "Season 01" / "Show Name - S01E01 - Pilot.mkv"
        assert _by_name(plan)["Show.Name.S01E01.mkv"].destination == expected
        assert {e.root for e in plan.entries} == {outer.resolve()}


def test_a_file_source_builds_under_its_own_folder(tmp_path: Path) -> None:
    folder = tmp_path / "Loose"
    folder.mkdir()
    video = folder / "Show.Name.S01E01.mkv"
    video.write_bytes(b"a")
    options = _tv_options(folder_rename=True, season_folders=False)

    plan = plan_queue([video], options, _show_name()).plan

    [entry] = plan.entries
    assert entry.destination == folder.resolve() / "Show Name" / "Show Name - S01E01 - Pilot.mkv"


def test_a_missing_source_and_a_file_source_that_is_not_a_video_are_reported(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    notes = tmp_path / "notes.txt"
    notes.write_text("n", encoding="utf-8")
    subtitle = tmp_path / "Show.Name.S01E01.srt"
    subtitle.write_text("s", encoding="utf-8")
    gone = tmp_path / "Gone"

    build = plan_queue(
        [gone, notes, subtitle, tmp_path / "Show.Name.S01E01.mkv"], _tv_options(), _show_name()
    )

    assert [e.source.name for e in build.plan.entries] == [
        "Show.Name.S01E01.mkv",
        "Show.Name.S01E01.srt",
    ]
    assert len(build.messages) == 3
    assert "no longer exists" in build.messages[0] and str(gone) in build.messages[0]
    assert "not a video" in build.messages[1] and "notes.txt" in build.messages[1]
    assert "not a video" in build.messages[2] and "Show.Name.S01E01.srt" in build.messages[2]


def test_a_video_whose_name_cannot_be_read_is_not_recognised_with_its_sidecars(
    tmp_path: Path,
) -> None:
    (tmp_path / "Holiday Clip.mkv").write_bytes(b"a")
    (tmp_path / "Holiday Clip.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Orphan.S01E01.nfo").write_text("n", encoding="utf-8")
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"b")

    plan = plan_queue([tmp_path], _tv_options(), _show_name()).plan

    entries = _by_name(plan)
    assert sorted(entries) == ["Holiday Clip.mkv", "Holiday Clip.srt", "Show.Name.S01E01.mkv"]
    for name in ("Holiday Clip.mkv", "Holiday Clip.srt"):
        assert entries[name].status is EntryStatus.NOT_RECOGNISED
        assert entries[name].destination is None
        assert entries[name].title is None
    assert entries["Show.Name.S01E01.mkv"].status is EntryStatus.READY
    assert [t.name for t in plan.titles] == ["Show Name"]


def test_a_group_the_search_finds_nothing_for_is_a_title_with_no_match(tmp_path: Path) -> None:
    (tmp_path / "Nowhere.Show.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Nowhere.Show.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Nowhere.Show.S02E03.mkv").write_bytes(b"b")

    plan = plan_queue([tmp_path], _tv_options(), _show_name()).plan

    [title] = plan.titles
    assert title.match is None
    assert title.candidates == ()
    assert title.name == "Nowhere Show"
    assert title.seasons == (1, 2)
    assert len(plan.entries) == 3
    for entry in plan.entries:
        assert entry.status is EntryStatus.NO_MATCH
        assert entry.destination is None
        assert entry.title == title


def test_a_tv_file_whose_episode_is_not_found_has_no_match_on_its_own(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E09.mkv").write_bytes(b"b")
    (tmp_path / "Show.Name.S01E09.srt").write_text("s", encoding="utf-8")

    plan = plan_queue([tmp_path], _tv_options(), _show_name()).plan

    entries = _by_name(plan)
    [title] = plan.titles
    assert title.match is not None
    assert entries["Show.Name.S01E01.mkv"].status is EntryStatus.READY
    for name in ("Show.Name.S01E09.mkv", "Show.Name.S01E09.srt"):
        assert entries[name].status is EntryStatus.NO_MATCH
        assert entries[name].destination is None
        assert entries[name].title == title


def test_a_lookup_failure_stops_the_build_with_the_providers_message(tmp_path: Path) -> None:
    class Failing(TvStandIn):
        def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
            raise ProviderError("TMDB rejected the API key (HTTP 401)")

    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")

    with pytest.raises(ProviderError, match="HTTP 401"):
        plan_queue([tmp_path], _tv_options(), Failing(shows={}, episodes={}))


def test_an_episode_lookup_failure_stops_the_build(tmp_path: Path) -> None:
    class Failing(TvStandIn):
        def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
            raise ProviderError("TheTVDB request failed with HTTP 503")

    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    stand_in = _show_name()

    with pytest.raises(ProviderError, match="HTTP 503"):
        plan_queue([tmp_path], _tv_options(), Failing(shows=stand_in.shows, episodes={}))


def test_groups_with_the_same_match_are_one_title(tmp_path: Path) -> None:
    (tmp_path / "Zed.Show.Name.S01E02.mkv").write_bytes(b"z")
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    stand_in = _show_name()
    stand_in.shows["zed show name"] = (
        Candidate(id="1", name="Show Name", year=2010, poster_ref="/p1.jpg"),
        Candidate(id="9", name="Zed", year=1999),
    )

    plan = plan_queue([tmp_path], _tv_options(), stand_in).plan

    [title] = plan.titles
    assert title.match is not None and title.match.id == "1"
    assert title.candidates == (Candidate(id="2", name="Show Name (2020)", year=2020),)
    assert {e.title for e in plan.entries} == {title}
    assert sorted(stand_in.searches) == ["Show Name", "Zed Show Name"]


def test_a_taken_name_gets_the_numbered_name_and_the_status_name_taken(tmp_path: Path) -> None:
    (tmp_path / "Show Name - S01E01 - Pilot.mkv").write_bytes(b"already here")
    (tmp_path / "The.Show.Name.S01E01.mkv").write_bytes(b"t")
    (tmp_path / "The.Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    stand_in = _show_name()
    stand_in.shows["the show name"] = stand_in.shows["show name"]
    queue = [tmp_path / "The.Show.Name.S01E01.mkv", tmp_path / "Show.Name.S01E01.mkv"]

    plan = plan_queue(queue, _tv_options(), stand_in).plan

    entries = _by_name(plan)
    first = entries["Show.Name.S01E01.mkv"]
    second = entries["The.Show.Name.S01E01.mkv"]
    sidecar = entries["The.Show.Name.S01E01.srt"]
    root = tmp_path.resolve()
    assert (first.destination, first.status) == (
        root / "Show Name - S01E01 - Pilot (1).mkv",
        EntryStatus.NAME_TAKEN,
    )
    assert (second.destination, second.status) == (
        root / "Show Name - S01E01 - Pilot (2).mkv",
        EntryStatus.NAME_TAKEN,
    )
    assert (sidecar.destination, sidecar.status) == (
        root / "Show Name - S01E01 - Pilot (2).srt",
        EntryStatus.READY,
    )


@dataclass
class FilmStandIn:
    """Answers film searches from fixed data keyed by (hint, year), and counts the calls."""

    films: dict[tuple[str, int | None], tuple[Candidate, ...]]
    searches: list[tuple[str, int | None]] = field(default_factory=list)

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append((hint, year))
        return self.films.get((hint.casefold().strip(), year), ())


def _film_options(**kwargs: object) -> PlanOptions:
    return _tv_options(mode=ScanMode.FILM, **kwargs)


def test_film_videos_are_grouped_by_title_hint_and_year_hint(tmp_path: Path) -> None:
    (tmp_path / "Harbour.Lights.2011.mkv").write_bytes(b"a")
    (tmp_path / "Harbour.Lights.2011.1080p.mkv").write_bytes(b"b")
    (tmp_path / "Harbour.Lights.2011.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Harbour.Lights.1962.mkv").write_bytes(b"c")
    (tmp_path / "Lost.Film.2003.mkv").write_bytes(b"d")
    harbour = Candidate(id="h11", name="Harbour Lights", year=2011, poster_ref="/h.jpg")
    old = Candidate(id="h62", name="Harbour Lights", year=1962)
    stand_in = FilmStandIn(
        films={("harbour lights", 2011): (harbour, old), ("harbour lights", 1962): (old,)},
    )
    options = _film_options(folder_rename=True)

    plan = plan_queue([tmp_path], options, stand_in).plan

    assert sorted(stand_in.searches, key=str) == [
        ("Harbour Lights", 1962),
        ("Harbour Lights", 2011),
        ("Lost Film", 2003),
        ("Lost Film", None),
    ]
    by_title = {(t.name, t.year): t for t in plan.titles}
    assert sorted(by_title) == [
        ("Harbour Lights", 1962),
        ("Harbour Lights", 2011),
        ("Lost Film", 2003),
    ]
    assert by_title[("Harbour Lights", 2011)].candidates == (old,)
    assert by_title[("Lost Film", 2003)].match is None
    root = tmp_path.resolve()
    entries = _by_name(plan)
    assert entries["Harbour.Lights.2011.1080p.mkv"].destination == (
        root / "Harbour Lights (2011)" / "Harbour Lights (2011).mkv"
    )
    assert entries["Harbour.Lights.2011.mkv"].destination == (
        root / "Harbour Lights (2011)" / "Harbour Lights (2011) (1).mkv"
    )
    assert entries["Harbour.Lights.2011.mkv"].status is EntryStatus.NAME_TAKEN
    assert entries["Harbour.Lights.2011.srt"].destination == (
        root / "Harbour Lights (2011)" / "Harbour Lights (2011) (1).srt"
    )
    assert entries["Harbour.Lights.1962.mkv"].destination == (
        root / "Harbour Lights (1962)" / "Harbour Lights (1962).mkv"
    )
    assert entries["Lost.Film.2003.mkv"].status is EntryStatus.NO_MATCH
    assert entries["Lost.Film.2003.mkv"].destination is None
    assert all(e.season is None and e.episode is None for e in plan.entries)


def test_a_film_whose_name_cannot_be_read_is_not_recognised(tmp_path: Path) -> None:
    (tmp_path / "2011.mkv").write_bytes(b"a")

    plan = plan_queue([tmp_path], _film_options(), FilmStandIn(films={})).plan

    [entry] = plan.entries
    assert entry.status is EntryStatus.NOT_RECOGNISED
    assert plan.titles == ()


def test_two_sources_that_want_one_name_get_numbered_names_in_source_path_order(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    for disc in ("disc b", "Disc A"):
        (tmp_path / disc).mkdir()
        (tmp_path / disc / "Show.Name.S01E01.mkv").write_bytes(disc.encode())
    options = _tv_options(destination_root=library, folder_rename=True, season_folders=True)

    plan = plan_queue([tmp_path / "disc b", tmp_path / "Disc A"], options, _show_name()).plan

    season = library / "Show Name" / "Season 01"
    assert [(e.source.parent.name, e.destination, e.status) for e in plan.entries] == [
        ("Disc A", season / "Show Name - S01E01 - Pilot.mkv", EntryStatus.READY),
        ("disc b", season / "Show Name - S01E01 - Pilot (1).mkv", EntryStatus.NAME_TAKEN),
    ]


def test_a_sidecar_whose_own_name_is_taken_is_numbered_while_its_video_is_ready(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Show Name - S01E01 - Pilot.srt").write_text("old", encoding="utf-8")

    plan = plan_queue([tmp_path / "Show.Name.S01E01.mkv"], _tv_options(), _show_name()).plan

    entries = _by_name(plan)
    assert entries["Show.Name.S01E01.mkv"].status is EntryStatus.READY
    sidecar = entries["Show.Name.S01E01.srt"]
    assert sidecar.status is EntryStatus.NAME_TAKEN
    assert sidecar.destination == tmp_path.resolve() / "Show Name - S01E01 - Pilot (1).srt"


def test_a_film_candidate_without_a_year_is_dropped(tmp_path: Path) -> None:
    (tmp_path / "Harbour.Lights.mkv").write_bytes(b"a")
    no_year = Candidate(id="x", name="Harbour Lights", year=None)
    harbour = Candidate(id="h11", name="Harbour Lights", year=2011)
    stand_in = FilmStandIn(films={("harbour lights", None): (no_year, harbour)})

    plan = plan_queue([tmp_path], _film_options(), stand_in).plan

    [title] = plan.titles
    assert (title.match, title.candidates) == (harbour, ())
    assert plan.entries[0].destination == tmp_path.resolve() / "Harbour Lights (2011).mkv"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges on Windows")
def test_a_symlinked_video_is_its_own_file_and_never_stands_in_for_its_target(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (b / "Show.Name.S01E01.mkv").write_bytes(b"real")
    (a / "Show.Name.S01E01.mkv").symlink_to(b / "Show.Name.S01E01.mkv")
    (b / "zlink.Show.Name.S01E02.mkv").symlink_to(b / "Show.Name.S01E01.mkv")

    plan = plan_queue([a, b], _tv_options(), _show_name()).plan

    assert [(e.root.name, e.source.name) for e in plan.entries] == [
        ("A", "Show.Name.S01E01.mkv"),
        ("B", "Show.Name.S01E01.mkv"),
        ("B", "zlink.Show.Name.S01E02.mkv"),
    ]


def test_a_name_taken_on_disk_and_wanted_by_two_sources_numbers_once_across_the_plan(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    season = library / "Show Name" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show Name - S01E01 - Pilot.mkv").write_bytes(b"already there")
    for disc in ("Disc A", "Disc B"):
        (tmp_path / disc).mkdir()
        (tmp_path / disc / "Show.Name.S01E01.mkv").write_bytes(disc.encode())
    options = _tv_options(destination_root=library, folder_rename=True, season_folders=True)

    plan = plan_queue([tmp_path / "Disc B", tmp_path / "Disc A"], options, _show_name()).plan

    assert [(e.source.parent.name, e.destination.name) for e in plan.entries if e.destination] == [
        ("Disc A", "Show Name - S01E01 - Pilot (1).mkv"),
        ("Disc B", "Show Name - S01E01 - Pilot (2).mkv"),
    ]
