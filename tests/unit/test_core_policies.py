"""Core policy enums."""

from __future__ import annotations

from termrenamer.core.policies import CollisionPolicy


def test_collision_policy_values() -> None:
    assert CollisionPolicy.SUFFIX.value == "suffix"
    assert CollisionPolicy.SKIP.value == "skip"
