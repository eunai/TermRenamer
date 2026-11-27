"""The Match picker on the Preview: ``t`` picks a different Match for the selected Title.

Driven by keys with stand-in Providers, read off the screen and the Plan.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from termrenamer.core.models import Candidate, EntryStatus
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.dialogs.match_picker import MatchPicker
from termrenamer.tui.stage import Stage
from termrenamer.util.errors import ProviderError

from .screen_driver import (
    FERRY,
    SHOW,
    SIZE,
    FilmStandIn,
    TvStandIn,
    build,
    footer_keys,
    lines_with,
    make_app,
    press,
    queue,
    screen_text,
    text_of,
    tv_backups,
    wiring,
)

HEAT = Candidate(id="949", name="Heat", year=1995)
HEAT_1986 = Candidate(id="31", name="Heat", year=1986)
HEAT_WAVE = Candidate(id="77", name="Heat Wave", year=1990)
LIGHTS_US = Candidate(id="40", name="Harbour Lights US", year=2022)


@dataclass
class Films(FilmStandIn):
    """Film searches from fixed data; a hint in ``failing`` fails as the Provider would."""

    failing: set[str] = field(default_factory=set)
    searches: list[tuple[str, int | None]] = field(default_factory=list)

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        self.searches.append((hint, year))
        if hint.casefold() in self.failing:
            msg = "TMDB answered 503: try again later."
            raise ProviderError(msg)
        return super().search_films(hint=hint, year=year)


def films() -> Films:
    return Films(
        films={
            ("heat", 1995): (HEAT, HEAT_1986, HEAT_WAVE),
            ("heat wave", 1990): (HEAT_WAVE,),
            ("heat", None): (HEAT, HEAT_1986),
            ("solo", None): (HEAT,),
        }
    )


@dataclass
class Shows(TvStandIn):
    """TV lookups from fixed data. With ``hold`` on a show id, its episode lookups wait
    until the test sets ``go``; an episode lookup of a show in ``failing`` fails."""

    hold_show: str | None = None
    holding: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    failing: set[str] = field(default_factory=set)

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        if show_id == self.hold_show:
            self.holding.set()
            self.release.wait(timeout=10)
        if show_id in self.failing:
            msg = "TheTVDB answered 401: the key was refused."
            raise ProviderError(msg)
        return super().episode_title(show_id=show_id, season=season, episode=episode)


def shows(**kwargs: object) -> Shows:
    return Shows(
        shows={
            "harbour lights": (SHOW, LIGHTS_US),
            "night ferry": (FERRY,),
            "lights": (LIGHTS_US, SHOW),
        },
        episodes={
            ("11", 1, 1): "The Tide Comes In",
            ("11", 1, 2): "Salt and Rope",
            ("12", 1, 1): "Cast Off",
            ("40", 1, 1): "Pilot",
        },
        **kwargs,  # type: ignore[arg-type]
    )


def film_backups(parent: Path) -> Path:
    folder = parent / "Films"
    folder.mkdir()
    for name in ("Heat.1995.mkv", "1080p.mkv", "1080p.srt", "Unknown.Film.2003.mkv"):
        (folder / name).write_bytes(b"x")
    return folder


def picker(app: TermRenamerApp) -> MatchPicker:
    assert isinstance(app.screen, MatchPicker)
    return app.screen


def picker_lines(app: TermRenamerApp) -> list[str]:
    """The picker's rows as the person reads them: mark, key and text."""
    shown = []
    for row in app.screen.query("ChoiceRow"):
        if row.display:
            mark = text_of(app, f"#{row.id} .choice-mark").strip()
            key = text_of(app, f"#{row.id} .choice-key").strip()
            words = text_of(app, f"#{row.id} .choice-text").strip()
            shown.append(" ".join(part for part in (mark, key, words) if part))
    return shown


async def film_preview(pilot: object, tmp_path: Path) -> None:
    await press(pilot, "m")  # type: ignore[arg-type]
    await queue(pilot, film_backups(tmp_path))  # type: ignore[arg-type]
    await build(pilot)  # type: ignore[arg-type]


async def settle(pilot: object) -> None:
    app = pilot.app  # type: ignore[attr-defined]
    await app.workers.wait_for_complete()
    for screen in app.screen_stack:
        await screen.workers.wait_for_complete()
    await pilot.pause()  # type: ignore[attr-defined]


# --------------------------------------------------------------------- Film


async def test_t_lists_the_current_match_the_next_candidate_and_type_a_title(
    tmp_path: Path,
) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        await press(pilot, "t")
        lines = picker_lines(app)
        now = text_of(app, "#picker-now")
        heading = str(app.screen.query_one("#picker-dialog").border_title)

    assert heading.strip() == "Pick a match for Heat (1995) · TMDB"
    assert now == "Now: Heat (1995)"
    assert lines == ["▸ 1 Heat (1995) (current)", "2 Heat (1986)", "/ Type a title"]


async def test_picking_a_film_candidate_renames_from_its_title_and_year(tmp_path: Path) -> None:
    provider = films()
    app = make_app(wiring(film=provider))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        searches = list(provider.searches)
        await press(pilot, "t")
        await press(pilot, "2")
        await settle(pilot)
        on_picker = isinstance(app.screen, MatchPicker)
        text = screen_text(app)
        heading = text_of(app, "#details-heading").splitlines()
        plan = app.plan

    assert not on_picker
    assert plan is not None
    heat = next(v for v in plan.videos if v.source.name == "Heat.1995.mkv")
    assert heat.destination is not None and heat.destination.name == "Heat (1986).mkv"
    assert provider.searches == searches
    assert "Heat (1995) now matches Heat (1986)." in text
    # The selection stays on the same Title.
    assert heading[0] == "Heat (1986)"


async def test_arrows_and_enter_choose_and_picking_the_current_match_changes_nothing(
    tmp_path: Path,
) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "down", "up", "enter")
        text = screen_text(app)
        kept = app.plan
        await press(pilot, "t")
        await press(pilot, "down")
        moved = picker_lines(app)
        await press(pilot, "enter")
        picked = app.plan

    assert kept is built
    assert "Kept the current match." in text
    assert moved[1] == "▸ 2 Heat (1986)"
    assert picked is not None and picked.titles[0].match == HEAT_1986


async def test_escape_closes_the_picker_with_the_plan_unchanged(tmp_path: Path) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "escape")
        stage = app.stage
        on_picker = isinstance(app.screen, MatchPicker)

    assert app.plan is built
    assert stage is Stage.PREVIEW
    assert not on_picker


async def test_typing_a_title_searches_again_and_the_results_replace_the_candidates(
    tmp_path: Path,
) -> None:
    provider = films()
    app = make_app(wiring(film=provider))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        await press(pilot, "t")
        await press(pilot, "slash")
        assert picker(app).typing
        app.screen.query_one("#picker-typed").value = "Heat Wave 1990"  # type: ignore[attr-defined]
        await press(pilot, "enter")
        await settle(pilot)
        lines = picker_lines(app)
        await press(pilot, "2")
        plan = app.plan

    assert ("Heat Wave", 1990) in provider.searches
    assert lines == ["1 Heat (1995) (current)", "▸ 2 Heat Wave (1990)", "/ Type a title"]
    assert plan is not None and plan.titles[0].match == HEAT_WAVE
    assert plan.titles[0].candidates == ()


async def test_a_search_with_one_result_shows_the_current_match_and_type_a_title_only(
    tmp_path: Path,
) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        await press(pilot, "t")
        await press(pilot, "slash")
        app.screen.query_one("#picker-typed").value = "Solo"  # type: ignore[attr-defined]
        await press(pilot, "enter")
        await settle(pilot)
        lines = picker_lines(app)

    assert lines == ["1 Heat (1995) (current)", "▸ / Type a title"]


async def test_a_typed_search_that_finds_nothing_says_so_in_the_picker(tmp_path: Path) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "slash")
        app.screen.query_one("#picker-typed").value = "Nothing Like It"  # type: ignore[attr-defined]
        await press(pilot, "enter")
        await settle(pilot)
        status = text_of(app, "#picker-status")
        lines = picker_lines(app)

    assert status == "Nothing found for “Nothing Like It”."
    assert lines == ["1 Heat (1995) (current)", "▸ / Type a title"]
    assert app.plan is built


async def test_a_typed_search_that_fails_shows_the_providers_message(tmp_path: Path) -> None:
    provider = films()
    provider.failing.add("broken")
    app = make_app(wiring(film=provider))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "slash")
        app.screen.query_one("#picker-typed").value = "Broken"  # type: ignore[attr-defined]
        await press(pilot, "enter")
        await settle(pilot)
        status = text_of(app, "#picker-status")
        await press(pilot, "escape")

    assert status == "TMDB answered 503: try again later. Nothing changed."
    assert app.plan is built


async def test_a_title_with_no_match_opens_on_no_match_found_and_the_typed_search(
    tmp_path: Path,
) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        rows = [row.name for row in app.query_one("#preview-titles").rows]  # type: ignore[attr-defined]
        await press(pilot, *["down"] * rows.index("Unknown Film (2003)"), "t")
        now = text_of(app, "#picker-now")
        lines = picker_lines(app)
        typing = picker(app).typing
        typed = app.screen.query_one("#picker-typed").value  # type: ignore[attr-defined]

    assert now == "No match found."
    assert lines == ["▸ / Type a title"]
    assert typing
    assert typed == "Unknown Film 2003"


async def test_a_not_recognised_film_is_matched_by_a_typed_title_and_forms_a_title(
    tmp_path: Path,
) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        rows = [row.name for row in app.query_one("#preview-titles").rows]  # type: ignore[attr-defined]
        await press(pilot, *["down"] * rows.index("1080p.mkv"), "t")
        now = text_of(app, "#picker-now")
        typed = app.screen.query_one("#picker-typed")
        prefilled = typed.value  # type: ignore[attr-defined]
        typed.value = "Heat Wave (1990)"  # type: ignore[attr-defined]
        await press(pilot, "enter")
        await settle(pilot)
        await press(pilot, "1")
        await settle(pilot)
        heading = text_of(app, "#details-heading").splitlines()
        plan = app.plan

    assert now == "Not recognised: 1080p.mkv"
    assert prefilled == "1080p"
    assert plan is not None
    named = {e.source.name: e.destination.name for e in plan.entries if e.destination}
    assert named["1080p.mkv"] == "Heat Wave (1990).mkv"
    assert named["1080p.srt"] == "Heat Wave (1990).srt"
    assert heading[0] == "Heat Wave (1990)"


async def test_two_titles_that_now_share_a_match_are_one_and_stay_selected(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Films"
    folder.mkdir()
    for name in ("Heat.1995.mkv", "Heat.1986.mkv"):
        (folder / name).write_bytes(b"x")
    provider = films()
    provider.films[("heat", 1986)] = (HEAT_1986, HEAT)
    app = make_app(wiring(film=provider))
    async with app.run_test(size=SIZE) as pilot:
        await press(pilot, "m")
        await queue(pilot, folder)
        await build(pilot)
        await press(pilot, "t")
        await press(pilot, "2")
        text = screen_text(app)
        heading = text_of(app, "#details-heading").splitlines()
        plan = app.plan

    assert plan is not None and len(plan.titles) == 1
    assert heading[0] == "Heat (1995)"
    assert len(lines_with(text, "Heat (1995)")) >= 1


async def test_a_new_build_from_the_queue_starts_afresh_after_a_pick(tmp_path: Path) -> None:
    app = make_app(wiring(film=films()))
    async with app.run_test(size=SIZE) as pilot:
        await film_preview(pilot, tmp_path)
        await press(pilot, "t")
        await press(pilot, "2")
        await press(pilot, "escape")
        await build(pilot)
        plan = app.plan

    assert plan is not None
    assert next(t for t in plan.titles if t.match is not None).match == HEAT


# ----------------------------------------------------------------------- TV


async def test_picking_a_tv_candidate_looks_its_episodes_up_off_the_screens_thread(
    tmp_path: Path,
) -> None:
    provider = shows(hold_show="40")
    app = make_app(wiring(tv=provider))
    async with app.run_test(size=(300, 40)) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        await press(pilot, "t")
        await press(pilot, "2")
        assert provider.holding.wait(timeout=5)
        await pilot.pause()
        looking = screen_text(app)
        keys_while_looking = footer_keys(app)
        await press(pilot, "enter", "x")
        refused = screen_text(app)
        provider.release.set()
        await settle(pilot)
        text = screen_text(app)
        heading = text_of(app, "#details-heading").splitlines()
        plan = app.plan

    assert any(line.endswith("looking up 2") for line in lines_with(looking, "Harbour Lights"))
    # Apply, Leave out and Change match wait for the lookups.
    assert not {"enter Apply…", "x Leave out", "t Match"} & set(keys_while_looking)
    assert "Looking up the episodes for the new Match. esc abandons the change." in refused
    assert plan is not None
    title = next(t for t in plan.titles if t.match == LIGHTS_US)
    videos = sorted((v for v in plan.videos if v.title == title), key=lambda v: v.episode or 0)
    assert [v.status for v in videos] == [EntryStatus.READY, EntryStatus.NO_MATCH]
    assert videos[0].destination is not None
    assert videos[0].destination.name == "Harbour Lights US - S01E01 - Pilot.mkv"
    assert "Harbour Lights now matches Harbour Lights US." in text
    assert heading[0] == "Harbour Lights US"


async def test_escape_during_the_episode_lookup_keeps_the_old_plan(tmp_path: Path) -> None:
    provider = shows(hold_show="40")
    app = make_app(wiring(tv=provider))
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "2")
        assert provider.holding.wait(timeout=5)
        await press(pilot, "escape")
        provider.release.set()
        await settle(pilot)
        text = screen_text(app)
        stage = app.stage

    assert app.plan is built
    assert stage is Stage.PREVIEW
    assert "Match change abandoned. The Plan is unchanged." in text
    assert any(line.endswith("ready 2") for line in lines_with(text, "Harbour Lights"))


async def test_a_failed_episode_lookup_keeps_the_old_plan_with_the_providers_message(
    tmp_path: Path,
) -> None:
    provider = shows(failing={"40"})
    app = make_app(wiring(tv=provider))
    async with app.run_test(size=(300, 40)) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        built = app.plan
        await press(pilot, "t")
        await press(pilot, "2")
        await settle(pilot)
        text = screen_text(app)

    assert app.plan is built
    assert "TheTVDB answered 401: the key was refused. The Plan is unchanged." in text


async def test_a_not_recognised_tv_file_says_matching_by_hand_is_not_available_yet(
    tmp_path: Path,
) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await queue(pilot, tv_backups(tmp_path))
        await build(pilot)
        built = app.plan
        await press(pilot, "down", "down", "t")
        text = screen_text(app)
        on_picker = isinstance(app.screen, MatchPicker)

    assert app.plan is built
    assert not on_picker
    assert "Matching a not recognised TV file by hand is not available yet." in text
