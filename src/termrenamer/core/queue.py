"""The queue: the ordered Sources of the current batch, held below the screen."""

from __future__ import annotations

from pathlib import Path

from termrenamer.util.errors import ValidationError


class SourceAlreadyQueuedError(ValidationError):
    """A Source whose resolved path is already in the queue."""


class SourceQueue:
    """The ordered list of queued Sources (files or folders), each a resolved path.

    A Source whose resolved path is already queued is refused; the comparison ignores
    letter case, as the source-path order does. Overlapping Sources (a folder and a
    file inside it) are accepted: planning plans each file once.
    """

    def __init__(self) -> None:
        self._sources: list[Path] = []

    @property
    def sources(self) -> tuple[Path, ...]:
        """The queued Sources, in the order they were added."""
        return tuple(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    def add(self, path: Path) -> Path:
        """Queue ``path`` and return its resolved form.

        Raises:
            SourceAlreadyQueuedError: The resolved path is already queued.
            OSError: The path cannot be resolved.
        """
        resolved = path.expanduser().resolve()
        key = str(resolved).casefold()
        if any(str(queued).casefold() == key for queued in self._sources):
            msg = f"Already queued: {resolved}"
            raise SourceAlreadyQueuedError(msg)
        self._sources.append(resolved)
        return resolved

    def clear(self) -> None:
        """Remove every Source."""
        self._sources.clear()
