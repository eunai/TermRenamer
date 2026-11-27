"""Policy enums for rename behaviour."""

from __future__ import annotations

from enum import StrEnum


class CollisionPolicy(StrEnum):
    """The Name taken setting: what a Plan does with a file whose new name is taken.

    ``SUFFIX`` adds a number such as `` (1)`` and applies the file; ``SKIP`` leaves the
    file where it is (``TERMRENAMER_NAME_TAKEN``).
    """

    SUFFIX = "suffix"
    SKIP = "skip"
