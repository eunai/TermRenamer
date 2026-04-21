"""Activity tab: layout, feed content, Logs unchanged, keyboard shortcut."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from textual.widgets import RichLog, TabbedContent, TabPane

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata, ScanMode
from termrenamer.observability.events import reset_default_bus_for_tests
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.widgets.activity_pane import ActivityPane
from termrenamer.wiring import PlanningWiring


@pytest.fixture(autouse=True)
def _reset_activity_bus() -> None:
    reset_default_bus_for_tests()
    yield


def _static_wiring() -> PlanningWiring:
    tv = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )
    film = StaticFilmMetadataProvider(
        _mapping={("show name", None): MovieMetadata(title="Show Name", year=2020)},
    )
    return PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)


@pytest.mark.asyncio
async def test_activity_tab_present_left_of_logs() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one("#bottom-tabs", TabbedContent)
        panes = list(tabs.query(TabPane))
        assert [p.id for p in panes] == ["tab-activity", "tab-logs"]
        assert tabs.active_pane is not None and tabs.active_pane.id == "tab-activity"


@pytest.mark.asyncio
async def test_logs_tab_unchanged() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#tab-logs") is not None
        assert app.query_one("#log_panel", RichLog) is not None
        # Logs RichLog is inside the inactive tab until first paint; show Logs so writes flush.
        app.query_one("#bottom-tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        app._log_line("hello logs unchanged")
        await pilot.pause()
        log = app.query_one("#log_panel", RichLog)
        assert len(log.lines) >= 1


@pytest.mark.asyncio
async def test_empty_state_visible_initially() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.query_one("#activity-pane", ActivityPane)
        log = pane.query_one("#activity-log", RichLog)
        empty = pane.query_one("#activity-empty")
        assert empty.display is True
        assert log.display is False


@pytest.mark.asyncio
async def test_activity_renders_tv_events(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        log = app.query_one("#activity-log", RichLog)
        assert len(log.lines) >= 2
        blob = "\n".join(str(line) for line in log.lines)
        assert "Show found: Show Name" in blob
        assert "Episode found: S01E01 - Pilot" in blob
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", blob)


@pytest.mark.asyncio
async def test_activity_renders_film_events(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.2020.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        log = app.query_one("#activity-log", RichLog)
        blob = "\n".join(str(line) for line in log.lines)
        assert "Film found: Show Name (2020)" in blob


@pytest.mark.asyncio
async def test_a_key_switches_to_activity_tab() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one("#bottom-tabs", TabbedContent)
        tabs.active = "tab-logs"
        await pilot.pause()
        assert tabs.active_pane is not None and tabs.active_pane.id == "tab-logs"
        await pilot.press("a")
        await pilot.pause()
        assert tabs.active_pane is not None and tabs.active_pane.id == "tab-activity"


def test_bindings_order_includes_a() -> None:
    """``a`` is preserved in the Phase 1 binding set (now a toggle, not force-Activity).

    Full order is exercised by ``test_tui_app.test_bindings_match_mock_order``.
    """
    keys = [b[0] for b in TermRenamerApp.BINDINGS]
    assert "a" in keys
    assert keys.index("a") == 3


@pytest.mark.asyncio
async def test_activity_autoscroll_skipped_without_scroll_simulation() -> None:
    """Scroll offset is environment-dependent; pause-on-scroll-up is covered manually."""
    pytest.skip("RichLog scroll simulation not asserted in CI (manual UX check).")
