"""Core policy enums."""

from __future__ import annotations

from termrenamer.core.policies import NameTakenPolicy


def test_name_taken_policy_values() -> None:
    assert NameTakenPolicy.SUFFIX.value == "suffix"
    assert NameTakenPolicy.SKIP.value == "skip"
