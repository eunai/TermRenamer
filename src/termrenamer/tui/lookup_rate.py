"""Lookups per second while the Plan is built: the rate and its small bar chart.

The clock is an argument, so a test can fix it; the screen uses :func:`time.monotonic`.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

_BLOCKS = "▁▂▃▄▅▆▇█"


class LookupRate:
    """Counts finished lookups against the time since it was made, when the build started."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._start = clock()
        self._times: list[float] = []

    def add(self) -> None:
        """One lookup finished now."""
        self._times.append(self.clock())

    def text(self) -> str:
        """The average rate since the start, such as ``7/s`` or ``1.5/s``."""
        elapsed = self.clock() - self._start
        if not self._times or elapsed <= 0:
            return "0/s"
        rate = len(self._times) / elapsed
        return f"{rate:.0f}/s" if rate >= 10 else f"{rate:.1f}/s"

    def chart(self, width: int) -> str:
        """One cell per second, the latest ``width`` seconds, each as tall as its lookups."""
        seconds = int(self.clock() - self._start) + 1
        counts = [0] * seconds
        for at in self._times:
            counts[min(seconds - 1, max(0, int(at - self._start)))] += 1
        counts = counts[-width:]
        top = max(counts, default=0)
        cells = "".join(
            _BLOCKS[max(0, math.ceil(n / top * len(_BLOCKS)) - 1)] if n else " " for n in counts
        )
        return cells.ljust(width)
