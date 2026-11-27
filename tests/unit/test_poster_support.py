"""Whether Posters can be shown: the posters extra, and a terminal that draws Sixel or Kitty images.

The check runs once at start, before the screen takes over the terminal. Stand-in
modules take the image package's place, so no test asks the real terminal.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from textual.widget import Widget

from termrenamer.persistence.posters import PosterError, PosterRequest
from termrenamer.tui.poster_support import (
    NO_IMAGES,
    NOT_INSTALLED,
    PosterSource,
    PosterSupport,
    detect_poster_support,
)

from .screen_driver import ImageHost, stand_in_image


class _Renderable:
    """A stand-in renderable class."""


class _Sixel(_Renderable): ...


class _Kitty(_Renderable): ...


class _Halfcell(_Renderable): ...


class _Unicode(_Renderable): ...


class _ImageWidget(Widget):
    def __init__(self, image: Path, *, on_error: Any = None) -> None:
        super().__init__()
        self.image = image
        self.on_error = on_error


class _SixelWidget(_ImageWidget): ...


class _KittyWidget(_ImageWidget): ...


def _loader(chosen: type[_Renderable]) -> Any:
    renderable = SimpleNamespace(
        Image=chosen,
        SixelImage=_Sixel,
        TGPImage=_Kitty,
        HalfcellImage=_Halfcell,
        UnicodeImage=_Unicode,
    )
    widget = SimpleNamespace(SixelImage=_SixelWidget, TGPImage=_KittyWidget)
    return lambda: (renderable, widget)


@pytest.mark.parametrize(("chosen", "widget"), [(_Sixel, _SixelWidget), (_Kitty, _KittyWidget)])
def test_sixel_or_kitty_makes_posters_available_with_that_protocols_widget(
    chosen: type[_Renderable], widget: type[_ImageWidget], tmp_path: Path
) -> None:
    support = detect_poster_support(_loader(chosen))

    assert support.available
    assert support.image is not None
    made = support.image(tmp_path / "a.poster", lambda exc: Widget())
    assert type(made) is widget
    assert isinstance(made, _ImageWidget) and made.image == tmp_path / "a.poster"
    assert made.on_error is not None


@pytest.mark.parametrize("chosen", [_Halfcell, _Unicode])
def test_the_character_block_fallbacks_are_never_used(chosen: type[_Renderable]) -> None:
    support = detect_poster_support(_loader(chosen))

    assert not support.available
    assert support.image is None
    assert support.reason == NO_IMAGES


def test_without_the_extra_posters_are_unavailable() -> None:
    def missing() -> Any:
        raise ImportError("No module named 'textual_image'")

    support = detect_poster_support(missing)

    assert not support.available
    assert support.reason == NOT_INSTALLED


def test_the_real_check_reports_the_extra_missing_when_the_package_is_absent() -> None:
    hidden = {name: None for name in sys.modules if name.startswith("textual_image.")}
    with mock.patch.dict(sys.modules, {"textual_image": None, **hidden}):
        support = detect_poster_support()

    assert support == PosterSupport(reason=NOT_INSTALLED)


def test_a_check_that_fails_leaves_posters_unavailable_with_its_reason() -> None:
    def broken() -> Any:
        raise OSError("stdin is closed")

    support = detect_poster_support(broken)

    assert not support.available
    assert "stdin is closed" in support.reason


def test_with_the_extra_installed_a_screen_that_is_no_terminal_draws_no_posters() -> None:
    """Under pytest the output is no terminal, so the package picks a fallback."""
    pytest.importorskip("textual_image")

    support = detect_poster_support()

    assert support.reason == NO_IMAGES
    assert not support.available


def test_main_checks_the_terminal_once_before_the_screen_starts() -> None:
    from termrenamer import __main__ as main_mod
    from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
    from termrenamer.wiring import PlanningWiring

    wired = PlanningWiring(
        tv_tmdb=StaticTvMetadataProvider(_mapping={}),
        tv_tvdb=None,
        film=StaticFilmMetadataProvider(_mapping={}),
        film_omdb=None,
    )
    order: list[str] = []
    support = PosterSupport(reason=NO_IMAGES)

    def detect() -> PosterSupport:
        order.append("check")
        return support

    def run(app: Any) -> None:
        order.append("run")
        assert app.poster_support is support

    with (
        mock.patch("termrenamer.wiring.bootstrap_wiring", return_value=(None, wired)),
        mock.patch("termrenamer.tui.poster_support.detect_poster_support", side_effect=detect),
        mock.patch("termrenamer.tui.app.TermRenamerApp.run", autospec=True, side_effect=run),
    ):
        main_mod.main()

    assert order == ["check", "run"]


def test_two_callers_of_one_poster_share_one_download_and_its_failure(tmp_path: Path) -> None:
    gate = threading.Event()
    host = ImageHost(status=404, gate=gate)
    source = PosterSource(store=host.store(tmp_path), image=stand_in_image)
    request = PosterRequest("tmdb", "/heat.jpg")
    errors: list[str] = []

    def ask() -> None:
        try:
            source.fetch(request)
        except PosterError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=ask)
    first.start()
    for _ in range(100):
        if host.requests:
            break
        time.sleep(0.01)
    second = threading.Thread(target=ask)
    second.start()
    time.sleep(0.05)
    gate.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert len(host.requests) == 1
    assert len(errors) == 2 and errors[0] == errors[1]
    # Once it has ended, a new call downloads again.
    gate.set()
    with pytest.raises(PosterError):
        source.fetch(request)
    assert len(host.requests) == 2
