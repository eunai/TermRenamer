"""The four Stages a batch goes through, in order."""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """One Stage of a batch: Queue, Plan, Preview, Applied."""

    QUEUE = "Queue"
    PLAN = "Plan"
    PREVIEW = "Preview"
    APPLIED = "Applied"

    @property
    def order(self) -> int:
        """The Stage's place in the order, from 0."""
        return list(Stage).index(self)
