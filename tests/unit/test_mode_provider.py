"""Mode/provider bar messages and Switch-based toggle behavior."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Label, Switch

from termrenamer.core.models import ScanMode
from termrenamer.tui.widgets.mode_provider_bar import (
    ModeProviderBar,
    OpenSettingsRequested,
    ProviderChanged,
    ScanModeChanged,
)

# Wider than default avoids edge cases if the bar grows; content fits in ~70 columns.
_MPB_TEST_SIZE: tuple[int, int] = (100, 24)


def _rgb_close(a: Color, b: Color, *, tol: int = 1) -> bool:
    """True if RGB channels match within tolerance (Rich vs hex parse can differ by 1)."""
    return abs(a.r - b.r) <= tol and abs(a.g - b.g) <= tol and abs(a.b - b.b) <= tol


def test_scan_mode_changed_message() -> None:
    m = ScanModeChanged(ScanMode.FILM)
    assert m.mode is ScanMode.FILM


def test_provider_changed_message() -> None:
    m = ProviderChanged("tmdb")
    assert m.provider_id == "tmdb"


def test_open_settings_requested_message_instantiates() -> None:
    """Empty sentinel message; proves the class is importable + constructable."""
    m = OpenSettingsRequested()
    assert isinstance(m, OpenSettingsRequested)


class _ModeProviderBarHost(App[None]):
    """Minimal host app so the bar can be driven by Pilot."""

    def __init__(self) -> None:
        super().__init__()
        self.mode_events: list[ScanModeChanged] = []
        self.provider_events: list[ProviderChanged] = []
        self.settings_events: list[OpenSettingsRequested] = []

    def compose(self) -> ComposeResult:
        yield ModeProviderBar(id="mpb")

    def on_scan_mode_changed(self, event: ScanModeChanged) -> None:
        self.mode_events.append(event)

    def on_provider_changed(self, event: ProviderChanged) -> None:
        self.provider_events.append(event)

    def on_open_settings_requested(self, event: OpenSettingsRequested) -> None:
        self.settings_events.append(event)


@pytest.mark.asyncio
async def test_initial_state_tv_and_tmdb_with_omdb_hidden() -> None:
    """TV is the initial mode; OMDb is masked (hidden) while TVDB/TMDB stay visible."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        assert app.query_one("#mode-toggle", Switch).value is False
        assert app.query_one("#provider-tmdb", Switch).value is True
        assert app.query_one("#provider-tvdb", Switch).value is False
        assert app.query_one("#provider-omdb", Switch).value is False
        assert app.query_one("#provider-omdb", Switch).display is False
        assert app.query_one("#provider-omdb-label", Label).display is False
        assert app.query_one("#provider-tvdb", Switch).display is True
        assert app.query_one("#provider-tmdb", Switch).display is True

        assert [e.mode for e in app.mode_events] == [ScanMode.TV]
        assert [e.provider_id for e in app.provider_events] == ["tmdb"]


@pytest.mark.asyncio
async def test_switch_to_film_masks_providers_and_keeps_tmdb() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        app.mode_events.clear()
        app.provider_events.clear()

        await pilot.click("#mode-toggle")
        await pilot.pause()

        assert app.query_one("#mode-toggle", Switch).value is True
        assert app.query_one("#provider-tvdb", Switch).display is False
        assert app.query_one("#provider-tvdb-label", Label).display is False
        assert app.query_one("#provider-omdb", Switch).display is True
        assert app.query_one("#provider-omdb-label", Label).display is True
        assert app.query_one("#provider-tmdb", Switch).value is True

        assert [e.mode for e in app.mode_events] == [ScanMode.FILM]
        assert app.provider_events == []


@pytest.mark.asyncio
async def test_switch_to_film_then_tv_forces_tmdb_when_tvdb_was_selected() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#provider-tvdb")
        await pilot.pause()
        assert app.query_one("#provider-tvdb", Switch).value is True

        app.mode_events.clear()
        app.provider_events.clear()

        await pilot.click("#mode-toggle")
        await pilot.pause()

        assert app.query_one("#provider-tmdb", Switch).value is True
        assert app.query_one("#provider-tvdb", Switch).value is False
        assert [e.mode for e in app.mode_events] == [ScanMode.FILM]
        assert [e.provider_id for e in app.provider_events] == ["tmdb"]


@pytest.mark.asyncio
async def test_selecting_omdb_in_film_mode_turns_off_tmdb() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#mode-toggle")
        await pilot.pause()
        app.mode_events.clear()
        app.provider_events.clear()

        await pilot.click("#provider-omdb")
        await pilot.pause()

        assert app.query_one("#provider-omdb", Switch).value is True
        assert app.query_one("#provider-tmdb", Switch).value is False
        assert app.mode_events == []
        assert [e.provider_id for e in app.provider_events] == ["omdb"]


@pytest.mark.asyncio
async def test_hidden_tvdb_cannot_be_selected_in_film_mode() -> None:
    """TVDB is hidden (``display = False``) in film mode and cannot be toggled on."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#mode-toggle")
        await pilot.pause()
        app.provider_events.clear()

        # Hidden switches cannot receive clicks; assert the mask directly and
        # prove that TMDB remains the selected provider.
        assert app.query_one("#provider-tvdb", Switch).display is False
        assert app.query_one("#provider-tvdb", Switch).value is False
        assert app.query_one("#provider-tmdb", Switch).value is True
        assert app.provider_events == []


_SWITCH_IDS: tuple[str, ...] = (
    "mode-toggle",
    "provider-tmdb",
    "provider-tvdb",
    "provider-omdb",
)


@pytest.mark.asyncio
async def test_bar_height_is_stable_two_rows() -> None:
    """``ModeProviderBar`` is a two-row second-header strip (reserved focus underline row)."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        assert bar.outer_size.height == 2


@pytest.mark.asyncio
async def test_bar_size_is_stable_across_focus_transitions() -> None:
    """Focusing any switch must not resize the bar (no vertical/horizontal jitter)."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        initial = (bar.outer_size.width, bar.outer_size.height)

        for sid in _SWITCH_IDS:
            sw = app.query_one(f"#{sid}", Switch)
            if sw.disabled or not sw.display:
                continue
            sw.focus()
            await pilot.pause()
            assert (bar.outer_size.width, bar.outer_size.height) == initial, (
                f"Bar resized when focusing #{sid}: initial={initial} now={bar.outer_size}"
            )

        app.set_focus(None)
        await pilot.pause()
        assert (bar.outer_size.width, bar.outer_size.height) == initial


@pytest.mark.asyncio
async def test_switch_size_is_stable_across_focus_transitions() -> None:
    """Regression: focusing a Switch must not resize it (no layout jitter).

    Stock ``Switch`` CSS uses a ``tall`` border that changes footprint on focus.
    ``ModeProviderBar`` pins ``border: none`` and reserves ``border-bottom: hkey``
    (blurred ``$boost``, focused ``$accent``) so ``outer_size`` stays identical
    blurred vs focused for every toggle.
    """
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()

        baseline_sizes: dict[str, tuple[int, int]] = {}
        for sid in _SWITCH_IDS:
            sw = app.query_one(f"#{sid}", Switch)
            if not sw.display:
                continue
            baseline_sizes[sid] = (sw.outer_size.width, sw.outer_size.height)

        for sid in _SWITCH_IDS:
            sw = app.query_one(f"#{sid}", Switch)
            if sw.disabled or not sw.display:
                continue
            blurred = (sw.outer_size.width, sw.outer_size.height)

            sw.focus()
            await pilot.pause()
            focused = (sw.outer_size.width, sw.outer_size.height)
            assert focused == blurred, (
                f"Switch #{sid} resized on focus: blurred={blurred} focused={focused}"
            )

            app.set_focus(None)
            await pilot.pause()
            re_blurred = (sw.outer_size.width, sw.outer_size.height)
            assert re_blurred == blurred

        for sid in _SWITCH_IDS:
            sw = app.query_one(f"#{sid}", Switch)
            if sid not in baseline_sizes:
                continue
            assert (sw.outer_size.width, sw.outer_size.height) == baseline_sizes[sid], (
                f"Switch #{sid} size changed after focus round-trip: "
                f"baseline={baseline_sizes[sid]} now={(sw.outer_size.width, sw.outer_size.height)}"
            )


@pytest.mark.asyncio
async def test_active_label_class_follows_selection() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        assert app.query_one("#mode-tv-label", Label).has_class("-active")
        assert not app.query_one("#mode-film-label", Label).has_class("-active")

        await pilot.click("#mode-toggle")
        await pilot.pause()
        assert app.query_one("#mode-film-label", Label).has_class("-active")
        assert not app.query_one("#mode-tv-label", Label).has_class("-active")


@pytest.mark.asyncio
@pytest.mark.parametrize("theme_name", ["solarized-light", "textual-dark"])
async def test_mode_toggle_slider_renders_success_in_both_tv_and_film(theme_name: str) -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        app.theme = theme_name
        await pilot.pause()
        sw = app.query_one("#mode-toggle", Switch)
        success = app.current_theme.success
        assert success is not None
        expected = Color.parse(success)

        tv_rich = sw.get_component_rich_style("switch--slider").color
        assert tv_rich is not None
        tv_color = Color.from_rich_color(tv_rich)

        await pilot.click("#mode-toggle")
        await pilot.pause()
        film_rich = sw.get_component_rich_style("switch--slider").color
        assert film_rich is not None
        film_color = Color.from_rich_color(film_rich)

        assert tv_color == film_color, (
            f"TV and Film #mode-toggle slider colors must match "
            f"(theme {theme_name!r}): tv={tv_color!r} film={film_color!r}"
        )
        assert _rgb_close(tv_color, expected), (
            f"#mode-toggle slider must match theme $success "
            f"(theme {theme_name!r}): got={tv_color!r} expected≈{expected!r}"
        )


@pytest.mark.asyncio
async def test_toggle_mode_method_cycles_tv_and_film() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        assert app.query_one("#mode-toggle", Switch).value is False

        app.mode_events.clear()
        bar.toggle_mode()
        await pilot.pause()

        assert app.query_one("#mode-toggle", Switch).value is True
        assert [e.mode for e in app.mode_events] == [ScanMode.FILM]
        assert app.query_one("#mode-film-label", Label).has_class("-active")

        app.mode_events.clear()
        bar.toggle_mode()
        await pilot.pause()

        assert app.query_one("#mode-toggle", Switch).value is False
        assert [e.mode for e in app.mode_events] == [ScanMode.TV]
        assert app.query_one("#mode-tv-label", Label).has_class("-active")


@pytest.mark.asyncio
async def test_cycle_provider_in_tv_mode_cycles_tmdb_tvdb() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        app.provider_events.clear()

        bar.cycle_provider()
        await pilot.pause()
        assert app.query_one("#provider-tmdb", Switch).value is False
        assert app.query_one("#provider-tvdb", Switch).value is True
        assert app.query_one("#provider-omdb", Switch).value is False
        assert [e.provider_id for e in app.provider_events] == ["tvdb"]

        app.provider_events.clear()
        bar.cycle_provider()
        await pilot.pause()
        assert app.query_one("#provider-tmdb", Switch).value is True
        assert app.query_one("#provider-tvdb", Switch).value is False
        assert [e.provider_id for e in app.provider_events] == ["tmdb"]


@pytest.mark.asyncio
async def test_cycle_provider_in_film_mode_cycles_tmdb_omdb() -> None:
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        await pilot.click("#mode-toggle")
        await pilot.pause()
        assert app.query_one("#provider-tvdb", Switch).display is False
        assert app.query_one("#provider-tvdb", Switch).value is False
        app.provider_events.clear()

        bar.cycle_provider()
        await pilot.pause()
        assert app.query_one("#provider-omdb", Switch).value is True
        assert app.query_one("#provider-tmdb", Switch).value is False
        assert app.query_one("#provider-tvdb", Switch).display is False
        assert [e.provider_id for e in app.provider_events] == ["omdb"]

        app.provider_events.clear()
        bar.cycle_provider()
        await pilot.pause()
        assert app.query_one("#provider-tmdb", Switch).value is True
        assert app.query_one("#provider-omdb", Switch).value is False
        assert [e.provider_id for e in app.provider_events] == ["tmdb"]


@pytest.mark.asyncio
async def test_settings_button_posts_open_settings_requested() -> None:
    """Clicking the inline ``#open-settings`` button posts ``OpenSettingsRequested``."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        assert app.settings_events == []
        await pilot.click("#open-settings")
        await pilot.pause()
        assert len(app.settings_events) == 1


@pytest.mark.asyncio
async def test_cycle_provider_ignores_hidden_providers() -> None:
    """TV mode: cycling never turns on OMDb (hidden for TV)."""
    app = _ModeProviderBarHost()
    async with app.run_test(size=_MPB_TEST_SIZE) as pilot:
        await pilot.pause()
        bar = app.query_one("#mpb", ModeProviderBar)
        assert app.query_one("#provider-omdb", Switch).display is False
        app.provider_events.clear()

        bar.cycle_provider()
        await pilot.pause()
        bar.cycle_provider()
        await pilot.pause()

        assert app.query_one("#provider-omdb", Switch).value is False
        assert [e.provider_id for e in app.provider_events] == ["tvdb", "tmdb"]
