"""Textual app: plan preview + confirm/cancel wiring (no live HTTP — static providers)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from textual.widgets import Button, Switch, Tree

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata, ScanMode
from termrenamer.tui.app import TermRenamerApp
from termrenamer.tui.widgets.mode_provider_bar import ModeProviderBar
from termrenamer.wiring import PlanningWiring


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
async def test_default_theme_is_gruvbox() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "gruvbox"


@pytest.mark.asyncio
async def test_build_plan_warns_with_empty_queue() -> None:
    """``b`` / Build plan on an empty queue surfaces the yellow hint (no crash)."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()


async def _queue_folder(app: TermRenamerApp, pilot: object, path: Path) -> None:
    """Phase 2 test helper: append ``path`` onto the queue post-mount.

    The app's fspicker callbacks (:meth:`TermRenamerApp._on_folder_picked`) mutate
    ``#source-tree`` synchronously, so mount must complete first. Callers should
    ``await pilot.pause()`` after to let any downstream message-driven updates
    flush.
    """
    app._on_folder_picked(path)


@pytest.mark.asyncio
async def test_build_plan_populates_table(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        src_tree = app.query_one("#source-tree", Tree)
        dst_tree = app.query_one("#dest-tree", Tree)
        assert len(src_tree.root.children) >= 1
        assert len(dst_tree.root.children) >= 1


@pytest.mark.asyncio
async def test_layout_regions_exist() -> None:
    """Phase 1 single-column layout: no ``#nav_panel`` / ``#content_row``."""
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    wiring = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#plan_panel") is not None
        assert app.query_one("#action-bar") is not None
        assert app.query_one("#tab-activity") is not None
        assert app.query_one("#tab-logs") is not None
        assert app.query_one("#log_panel") is not None
        assert not app.query("#nav_panel"), "#nav_panel must be removed in Phase 1"
        assert not app.query("#content_row"), "#content_row must be removed in Phase 1"


@pytest.mark.asyncio
async def test_mode_bar_docks_at_bottom_of_main_above_footer() -> None:
    """Mode/provider bar is the last child of ``#main`` (docks above the Footer)."""
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    wiring = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one("#mode-bar", ModeProviderBar)
        parent = bar.parent
        assert parent is not None and parent.id == "main"
        assert parent.children[-1] is bar, (
            "ModeProviderBar must be the last child of #main so it docks above Footer"
        )


@pytest.mark.asyncio
async def test_plan_panel_has_border_title_queue() -> None:
    """``#plan_panel`` renders the ``queue`` border title after mount."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one("#plan_panel")
        assert panel.border_title == " queue "


@pytest.mark.asyncio
async def test_bottom_tabs_has_border_title_output() -> None:
    """``#bottom-tabs`` renders the ``output`` border title after mount."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one("#bottom-tabs")
        assert tabs.border_title == " output "


@pytest.mark.asyncio
async def test_action_bar_has_six_buttons_in_mock_order() -> None:
    """Action bar ports the mock's six-button layout (add-files first; spacer before clear)."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        ids = [b.id for b in app.query("#action-bar Button")]
        assert ids == [
            "add-files",
            "add-folders",
            "build-plan",
            "confirm-apply",
            "clear-queue",
            "cancel-plan",
        ]


def test_command_palette_disabled() -> None:
    """Textual's Ctrl+P command palette must be disabled so ``p`` stays a toggle."""
    assert TermRenamerApp.ENABLE_COMMAND_PALETTE is False


def test_queue_is_empty_on_init() -> None:
    """The ``_queue`` scaffolding exists from Phase 1 (populated in Phase 2)."""
    app = TermRenamerApp(wiring=_static_wiring())
    assert app._queue == []


@pytest.mark.asyncio
async def test_queue_records_folder_path_after_picker_callback(tmp_path: Path) -> None:
    """The folder-picker callback appends the resolved folder onto ``_queue``."""
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._queue == []
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        assert app._queue == [tmp_path.resolve()]


@pytest.mark.asyncio
async def test_build_plan_provider_error_logged(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    wiring = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()


@pytest.mark.asyncio
async def test_build_plan_unexpected_exception_logged(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        with mock.patch(
            "termrenamer.tui.app.build_rename_plan",
            side_effect=RuntimeError("boom"),
        ):
            await pilot.press("b")
            await pilot.pause()


@pytest.mark.asyncio
async def test_confirm_buttons_disabled_before_plan() -> None:
    """Confirm and Cancel buttons must be disabled until a plan is built."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#confirm-apply", Button).disabled is True
        assert app.query_one("#cancel-plan", Button).disabled is True


@pytest.mark.asyncio
async def test_confirm_buttons_enabled_after_plan(tmp_path: Path) -> None:
    """After building a plan, confirm and cancel become clickable."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert app.query_one("#confirm-apply", Button).disabled is False
        assert app.query_one("#cancel-plan", Button).disabled is False


@pytest.mark.asyncio
async def test_cancel_clears_plan_without_apply(tmp_path: Path) -> None:
    """Pressing Cancel discards the plan; no filesystem mutation."""
    src = tmp_path / "Show.Name.S01E01.mkv"
    src.write_bytes(b"data")
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert app.current_plan is not None
        cancel_btn = app.query_one("#cancel-plan", Button)
        assert cancel_btn.disabled is False
        app.on_button_pressed(Button.Pressed(cancel_btn))
        await pilot.pause()
        assert app.current_plan is None
        assert src.exists(), "Cancel must not mutate the filesystem"
        assert app.query_one("#confirm-apply", Button).disabled is True


@pytest.mark.asyncio
async def test_confirm_apply_renames_files(tmp_path: Path) -> None:
    """Pressing Confirm apply runs apply_plan(confirmed=True) and moves files."""
    src = tmp_path / "Show.Name.S01E01.mkv"
    src.write_bytes(b"content")
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _queue_folder(app, pilot, tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert app.current_plan is not None
        confirm_btn = app.query_one("#confirm-apply", Button)
        assert confirm_btn.disabled is False
        app.on_button_pressed(Button.Pressed(confirm_btn))
        await pilot.pause()
        assert not src.exists(), "File should have been renamed by apply"
        assert app.current_plan is None
        assert app.query_one("#confirm-apply", Button).disabled is True


@pytest.mark.asyncio
async def test_m_key_toggles_scan_mode() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.scan_mode is ScanMode.TV
        assert app.query_one("#mode-toggle", Switch).value is False

        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
        assert app.query_one("#mode-toggle", Switch).value is True

        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.TV
        assert app.query_one("#mode-toggle", Switch).value is False


def test_footer_shows_toggle_mode_binding() -> None:
    assert ("m", "toggle_mode", "Toggle Mode") in TermRenamerApp.BINDINGS


def test_footer_shows_toggle_provider_binding() -> None:
    assert ("p", "toggle_provider", "Toggle Provider") in TermRenamerApp.BINDINGS


def test_bindings_match_mock_order() -> None:
    """Phase 1 binding swap: ``q`` → ``ctrl+q``; add ``ctrl+f``/``f1``/``ctrl+comma``."""
    assert [b[0] for b in TermRenamerApp.BINDINGS] == [
        "m",
        "p",
        "b",
        "a",
        "ctrl+f",
        "f1",
        "ctrl+comma",
        "ctrl+q",
    ]


def test_quit_binding_moved_to_ctrl_q() -> None:
    """Plain ``q`` must no longer be bound (conflicts with future query/text input)."""
    keys = [b[0] for b in TermRenamerApp.BINDINGS]
    assert "ctrl+q" in keys
    assert "q" not in keys


def test_a_binding_is_toggle_bottom_tab() -> None:
    """``a`` toggles between Activity/Logs (not force-Activity)."""
    assert ("a", "toggle_bottom_tab", "Activity / Logs") in TermRenamerApp.BINDINGS


@pytest.mark.asyncio
async def test_a_key_toggles_bottom_tab() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import TabbedContent

        tabs = app.query_one("#bottom-tabs", TabbedContent)
        initial = tabs.active
        await pilot.press("a")
        await pilot.pause()
        flipped = tabs.active
        assert flipped != initial
        await pilot.press("a")
        await pilot.pause()
        assert tabs.active == initial


@pytest.mark.asyncio
async def test_p_key_cycles_provider_in_tv_mode() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.provider_id == "tmdb"

        await pilot.press("p")
        await pilot.pause()
        assert app.provider_id == "tvdb"

        await pilot.press("p")
        await pilot.pause()
        assert app.provider_id == "tmdb"


@pytest.mark.asyncio
async def test_p_key_cycles_provider_in_film_mode() -> None:
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        assert app.scan_mode is ScanMode.FILM
        assert app.provider_id == "tmdb"

        await pilot.press("p")
        await pilot.pause()
        assert app.provider_id == "omdb"

        await pilot.press("p")
        await pilot.pause()
        assert app.provider_id == "tmdb"


@pytest.mark.asyncio
async def test_confirm_without_plan_logs_warning() -> None:
    """Confirm with no plan should not crash."""
    app = TermRenamerApp(wiring=_static_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._apply_current_plan()
        await pilot.pause()
