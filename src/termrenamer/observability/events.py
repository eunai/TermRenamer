"""In-process activity event bus for the TUI Activity tab and future observability.

TODO: Add ``filter_by(predicate: Callable[[ActivityEvent], bool])`` on
:class:`ActivityEventBus` when the UI needs filtering by show title or outcome kind.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_LOG = logging.getLogger(__name__)


class ActivityEventKind(StrEnum):
    """Activity feed entry kinds.

    Payload keys are convention-based strings (``show``, ``season``, ``episode``, …).
    Future kinds (rename applied, conflict resolved, dry-run preview) reuse the same
    :class:`ActivityEvent` shape without schema migration.
    """

    SHOW_FOUND = "show_found"
    EPISODE_FOUND = "episode_found"
    FILM_FOUND = "film_found"
    # Reserved for future wiring (no emit sites yet):
    # RENAME_APPLIED = "rename_applied"
    # RENAME_SKIPPED = "rename_skipped"
    # RENAME_FAILED = "rename_failed"
    # CONFLICT_RESOLVED = "conflict_resolved"


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """A single timestamped activity item for the Activity tab."""

    kind: ActivityEventKind
    timestamp: datetime
    payload: Mapping[str, str]
    """Free-form string fields (e.g. show title, episode code). Extensible without
    changing this dataclass.
    """


Subscriber = Callable[[ActivityEvent], None]
Unsubscribe = Callable[[], None]


class ActivityEventBus:
    """Lightweight pub/sub for :class:`ActivityEvent` (default process-wide instance)."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> Unsubscribe:
        """Register ``callback``; return a callable that removes the subscription."""

        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with suppress(ValueError):
                self._subscribers.remove(callback)

        return _unsubscribe

    def emit(self, event: ActivityEvent) -> None:
        """Deliver ``event`` to all subscribers; isolate subscriber failures."""

        for cb in list(self._subscribers):
            try:
                cb(event)
            except Exception:
                _LOG.exception("Activity subscriber failed; continuing with others")


_default_bus: ActivityEventBus | None = None


def default_bus() -> ActivityEventBus:
    """Process-wide bus so ``core/`` can emit without importing the TUI."""

    global _default_bus
    if _default_bus is None:
        _default_bus = ActivityEventBus()
    return _default_bus


def reset_default_bus_for_tests() -> None:
    """Replace the default bus with a fresh instance (pytest isolation)."""

    global _default_bus
    _default_bus = ActivityEventBus()


def emit_event(name: str, **fields: object) -> None:
    """Legacy no-op hook for future cross-cutting observability (tests, metrics)."""

    _ = (name, fields)
