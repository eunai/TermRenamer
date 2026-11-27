"""The Logs view's lines: every log record of the session, and every message the screen gives.

While the screen runs, :class:`LogBookHandler` takes the place of the stderr handler,
so library logs land here and never write over the screen. Records can arrive from a
build's thread; the book is safe to add to from any thread.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections import deque
from collections.abc import Callable

from termrenamer.util.logging import MaskingFormatter, failed_line


class LogBook:
    """The session's log lines, oldest first, keeping the last ``limit``.

    Each line has a number, counting from 1, so a reader can ask for the lines after
    the last one it has.
    """

    def __init__(self, limit: int = 5000) -> None:
        self._lines: deque[tuple[int, str]] = deque(maxlen=limit)
        self._count = 0
        self._lock = threading.Lock()

    def add(self, line: str) -> None:
        with self._lock:
            self._count += 1
            self._lines.append((self._count, line))

    def lines_after(self, number: int) -> tuple[tuple[int, str], ...]:
        """The kept lines numbered above ``number``, with their numbers."""
        with self._lock:
            return tuple(item for item in self._lines if item[0] > number)


class LogBookHandler(logging.Handler):
    """Writes each record to a :class:`LogBook`, then calls ``on_line``."""

    def __init__(self, book: LogBook, on_line: Callable[[], None]) -> None:
        super().__init__()
        self._book = book
        self._on_line = on_line
        self.setFormatter(MaskingFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self._book.add(line)
            self._on_line()
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - logging's name
        """Add :func:`failed_line` to the book, in place of logging's report, which prints
        the record's arguments; nothing when even that fails."""
        with contextlib.suppress(Exception):  # nothing more can be written
            self._book.add(failed_line(record))
