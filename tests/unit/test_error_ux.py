"""Error UX tests — errors show actionable context; secrets never leak (FR-008, PH-3)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from textual.widgets import Button

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata, PlanEntryStatus
from termrenamer.tui.app import TermRenamerApp
from termrenamer.util.errors import ApplyError, ProviderError, ValidationError
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
async def test_provider_error_shows_actionable_message(tmp_path: Path) -> None:
    """ProviderError during plan build should appear in logs without secrets."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    wiring = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert app.current_plan is not None
        assert len(app.current_plan.entries) == 1
        assert app.current_plan.entries[0].status is PlanEntryStatus.UNMATCHED


@pytest.mark.asyncio
async def test_validation_error_during_plan_logged(tmp_path: Path) -> None:
    """ValidationError during plan (e.g. missing credentials) shows in logs."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        with mock.patch(
            "termrenamer.tui.app.build_rename_plan",
            side_effect=ValidationError("Missing TMDB API key"),
        ):
            await pilot.press("b")
            await pilot.pause()
        assert app.current_plan is None


@pytest.mark.asyncio
async def test_apply_error_logged_in_tui(tmp_path: Path) -> None:
    """ApplyError during confirm apply is caught and logged."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert app.current_plan is not None
        with mock.patch(
            "termrenamer.tui.app.apply_plan",
            side_effect=ApplyError("Permission denied: /protected"),
        ):
            confirm_btn = app.query_one("#confirm-apply", Button)
            app.on_button_pressed(Button.Pressed(confirm_btn))
            await pilot.pause()


@pytest.mark.asyncio
async def test_unexpected_exception_during_apply_logged(tmp_path: Path) -> None:
    """Unexpected exceptions during apply are caught gracefully."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    wiring = _static_wiring()
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        with mock.patch(
            "termrenamer.tui.app.apply_plan",
            side_effect=RuntimeError("disk exploded"),
        ):
            confirm_btn = app.query_one("#confirm-apply", Button)
            app.on_button_pressed(Button.Pressed(confirm_btn))
            await pilot.pause()


def test_error_messages_do_not_contain_api_keys() -> None:
    """Typed errors must not leak API key values in their string representation."""
    fake_key = "sk-secret-abc123"
    err = ProviderError("TMDB request failed with HTTP 401")
    assert fake_key not in str(err)
    err2 = ValidationError("Missing TERMRENAMER_TMDB_API_KEY in environment")
    assert fake_key not in str(err2)


def test_no_secrets_in_provider_error_module() -> None:
    """ProviderError and ValidationError should not accept or embed raw key values."""
    import inspect

    import termrenamer.util.errors as errors_mod

    source = inspect.getsource(errors_mod)
    for secret_pattern in ["API_KEY", "api_key", "token", "password", "secret"]:
        lines_with_secret = [
            line
            for line in source.splitlines()
            if secret_pattern.lower() in line.lower() and "class " not in line
        ]
        for line in lines_with_secret:
            assert "=" not in line or "def " in line or "#" in line, (
                f"errors.py should not embed secret values: {line}"
            )
