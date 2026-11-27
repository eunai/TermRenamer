"""Builds through the real wiring, Providers and a cache file under tmp_path.

The Providers talk to a fake transport that answers with recorded-shape JSON
(made-up values) and records every request; nothing reaches the network.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import httpx
import pytest

from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.app_bootstrap import Settings
from termrenamer.core.models import PlanEntryStatus, RenamePlan, ScanMode
from termrenamer.core.planning import build_rename_plan, merge_rename_plans
from termrenamer.util.http import HttpClient, HttpClientConfig
from termrenamer.wiring import PlanningWiring, build_planning_wiring

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "api_responses"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _settings(cache: Path | None) -> Settings:
    return Settings(
        tmdb_api_key="tmdb-test-key",
        tvdb_api_key="tvdb-test-key",
        tvdb_subscriber_pin=None,
        omdb_api_key="omdb-test-key",
        http_timeout_seconds=5.0,
        http_max_attempts=1,
        http_backoff_base_seconds=0.01,
        http_jitter=False,
        cache_db_path=cache,
        log_file_path=None,
        film_dest_folder=None,
        tv_dest_folder=None,
        enable_folder_rename=False,
        enable_season_folders=False,
    )


class Recorder:
    """A fake transport: answers by host and path, and keeps each request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path, params = request.url.host, request.url.path, request.url.params
        if host == "api.themoviedb.org":
            if path == "/3/search/tv":
                return httpx.Response(200, json=_load("tmdb_search_tv_candidates.json"))
            if path.startswith("/3/tv/7001/season/1/episode/"):
                number = path.rsplit("/", 1)[1]
                return httpx.Response(200, json={"name": f"Chapter {number}"})
            if path == "/3/search/movie":
                if params.get("year") == "2026":
                    return httpx.Response(200, json={"page": 1, "results": []})
                return httpx.Response(200, json=_load("tmdb_search_movie_candidates.json"))
        if host == "api4.thetvdb.com":
            if path == "/v4/login":
                return httpx.Response(200, json=_load("tvdb_login.json"))
            if path == "/v4/search":
                return httpx.Response(200, json=_load("tvdb_search_series_candidates.json"))
            if path == "/v4/series/81001/episodes/default":
                episodes = [
                    {"seasonNumber": 1, "number": n, "name": f"Episode {n}"} for n in (1, 2, 3)
                ]
                return httpx.Response(200, json={"data": {"episodes": episodes}})
        if host == "www.omdbapi.com" and "s" in params:
            return httpx.Response(200, json=_load("omdb_search_films.json"))
        return httpx.Response(404, json={})

    def count(self, host: str, path: str | None = None) -> int:
        return sum(
            1 for r in self.requests if r.url.host == host and (path is None or r.url.path == path)
        )


def _wiring(tmp_path: Path, recorder: Recorder, *, cache: bool = True) -> PlanningWiring:
    settings = _settings(tmp_path / "cache" / "lookups.db" if cache else None)
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    http = HttpClient(config=HttpClientConfig(max_attempts=1), client=client)
    return build_planning_wiring(settings, http)


def _build(
    wiring: PlanningWiring, roots: list[Path], *, mode: ScanMode, provider_id: str
) -> RenamePlan:
    """Build one plan the way the app does: one lookup for every root of the build."""
    lookup: TvLookup | FilmLookup
    if mode is ScanMode.TV:
        lookup = wiring.resolve_tv(provider_id=provider_id)
    else:
        lookup = wiring.resolve_film(provider_id=provider_id)
    plans = [
        build_rename_plan(
            root=root,
            mode=mode,
            provider=lookup,
            enable_folder_rename=False,
        )
        for root in roots
    ]
    return merge_rename_plans(plans)


def _names(plan: RenamePlan) -> dict[str, str]:
    return {e.source.name: e.destination.name for e in plan.entries}


def _tv_roots(tmp_path: Path) -> list[Path]:
    roots = [tmp_path / "disc1", tmp_path / "disc2"]
    for root in roots:
        root.mkdir()
    (roots[0] / "Quiet.Valley.S01E01.mkv").write_bytes(b"1")
    (roots[0] / "Quiet.Valley.S01E02.mkv").write_bytes(b"2")
    (roots[1] / "quiet valley S01E03.mkv").write_bytes(b"3")
    return roots


def _film_root(tmp_path: Path) -> Path:
    root = tmp_path / "films"
    root.mkdir()
    (root / "Harbour.Lights.2011.mkv").write_bytes(b"f")
    (root / "Harbour.Lights.2011.Extended.mkv").write_bytes(b"g")
    return root


def test_omdb_lookups_are_served_from_the_cache_on_a_second_build(tmp_path: Path) -> None:
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder)
    root = _film_root(tmp_path)

    first = _build(wiring, [root], mode=ScanMode.FILM, provider_id="omdb")
    sent = recorder.count("www.omdbapi.com")
    second = _build(wiring, [root], mode=ScanMode.FILM, provider_id="omdb")

    assert sent == 1
    assert recorder.count("www.omdbapi.com") == 1
    assert _names(first) == _names(second)
    assert _names(first) == {
        "Harbour.Lights.2011.Extended.mkv": "Harbour Lights (2011).mkv",
        "Harbour.Lights.2011.mkv": "Harbour Lights (2011) (1).mkv",
    }


def test_a_second_build_on_another_thread_is_served_from_the_cache(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder)
    roots = _tv_roots(tmp_path)
    plans: list[RenamePlan] = []

    def run(provider_id: str) -> None:
        plans.append(_build(wiring, roots, mode=ScanMode.TV, provider_id=provider_id))

    for _ in range(2):
        worker = threading.Thread(target=run, args=("tmdb",))
        worker.start()
        worker.join()

    assert len(plans) == 2
    assert recorder.count("api.themoviedb.org", "/3/search/tv") == 1
    assert recorder.count("api.themoviedb.org") == 1 + 3
    assert _names(plans[0]) == _names(plans[1])
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_lookup_stored_from_one_provider_is_never_returned_for_another(tmp_path: Path) -> None:
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder)
    roots = _tv_roots(tmp_path)
    film_root = _film_root(tmp_path)

    tmdb_tv = _build(wiring, roots, mode=ScanMode.TV, provider_id="tmdb")
    tvdb_tv = _build(wiring, roots, mode=ScanMode.TV, provider_id="tvdb")
    assert recorder.count("api4.thetvdb.com", "/v4/search") == 1
    assert _names(tmdb_tv)["Quiet.Valley.S01E01.mkv"] == "Quiet Valley - S01E01 - Chapter 1.mkv"
    assert _names(tvdb_tv)["Quiet.Valley.S01E01.mkv"] == "Quiet Valley - S01E01 - Episode 1.mkv"

    _build(wiring, [film_root], mode=ScanMode.FILM, provider_id="tmdb")
    _build(wiring, [film_root], mode=ScanMode.FILM, provider_id="omdb")
    assert recorder.count("www.omdbapi.com") == 1


def test_a_build_searches_once_per_group_and_fetches_an_episode_list_once_per_show(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder, cache=False)
    roots = _tv_roots(tmp_path)

    plan = _build(wiring, roots, mode=ScanMode.TV, provider_id="tvdb")

    assert recorder.count("api4.thetvdb.com", "/v4/search") == 1
    assert recorder.count("api4.thetvdb.com", "/v4/series/81001/episodes/default") == 1
    assert {e.status for e in plan.entries} == {PlanEntryStatus.MATCHED}

    _build(wiring, roots, mode=ScanMode.TV, provider_id="tvdb")
    assert recorder.count("api4.thetvdb.com", "/v4/series/81001/episodes/default") == 2


def test_a_film_group_whose_search_with_a_year_found_nothing_searches_twice(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder)
    root = tmp_path / "films"
    root.mkdir()
    (root / "Harbour.Lights.2026.mkv").write_bytes(b"f")
    (root / "Harbour.Lights.2026.Remux.mkv").write_bytes(b"g")

    plan = _build(wiring, [root], mode=ScanMode.FILM, provider_id="tmdb")

    assert recorder.count("api.themoviedb.org", "/3/search/movie") == 2
    assert set(_names(plan).values()) == {
        "Harbour Lights (2011).mkv",
        "Harbour Lights (2011) (1).mkv",
    }

    _build(wiring, [root], mode=ScanMode.FILM, provider_id="tmdb")
    assert recorder.count("api.themoviedb.org", "/3/search/movie") == 2


def test_a_plan_takes_the_first_candidate_as_before(tmp_path: Path) -> None:
    recorder = Recorder()
    wiring = _wiring(tmp_path, recorder, cache=False)
    roots = _tv_roots(tmp_path)

    plan = _build(wiring, roots, mode=ScanMode.TV, provider_id="tmdb")

    assert _names(plan) == {
        "Quiet.Valley.S01E01.mkv": "Quiet Valley - S01E01 - Chapter 1.mkv",
        "Quiet.Valley.S01E02.mkv": "Quiet Valley - S01E02 - Chapter 2.mkv",
        "quiet valley S01E03.mkv": "Quiet Valley - S01E03 - Chapter 3.mkv",
    }
