"""Entry point smoke tests."""

from __future__ import annotations

from unittest import mock

import pytest

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.util.errors import ValidationError
from termrenamer.wiring import PlanningWiring


def test_main_exits_on_validation_error() -> None:
    from termrenamer import __main__ as main_mod

    with (
        mock.patch(
            "termrenamer.wiring.bootstrap_wiring",
            side_effect=ValidationError("no key"),
        ),
        pytest.raises(SystemExit) as ei,
    ):
        main_mod.main()
    assert ei.value.code == 2


def test_main_runs_app() -> None:
    from termrenamer import __main__ as main_mod

    tv = StaticTvMetadataProvider(_mapping={})
    film = StaticFilmMetadataProvider(_mapping={})
    wiring = PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)

    class Done(Exception):
        pass

    with (
        mock.patch("termrenamer.wiring.bootstrap_wiring", return_value=(None, wiring)),
        mock.patch("termrenamer.tui.app.TermRenamerApp.run", side_effect=Done),
        pytest.raises(Done),
    ):
        main_mod.main()
