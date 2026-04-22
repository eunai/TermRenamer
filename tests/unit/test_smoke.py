"""Smoke import tests for scaffold."""

from __future__ import annotations


def test_package_version() -> None:
    import termrenamer

    assert termrenamer.__version__ == "0.12.0"


def test_tui_actions_module_is_importable() -> None:
    """Spec §3 lists ``tui/actions.py`` for layout parity."""

    import termrenamer.tui.actions as actions

    assert actions.__all__ == []
