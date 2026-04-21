"""Policy enums for rename behavior."""

from __future__ import annotations

from enum import StrEnum


class CollisionPolicy(StrEnum):
    """How to handle destination conflicts."""

    SUFFIX = "suffix"
    SKIP = "skip"
