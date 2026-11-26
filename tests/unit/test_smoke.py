"""Smoke import tests for scaffold."""

from __future__ import annotations


def test_tui_actions_module_is_importable() -> None:
    """``tui/actions.py`` exists for layout parity and stays importable."""

    import termrenamer.tui.actions as actions

    assert actions.__all__ == []
