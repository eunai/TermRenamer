"""Smoke import tests for scaffold."""

from __future__ import annotations


def test_package_version() -> None:
    import termrenamer

    assert termrenamer.__version__ == "0.9.0"
