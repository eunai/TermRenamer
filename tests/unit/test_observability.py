"""Observability hooks."""

from __future__ import annotations

from termrenamer.observability.events import emit_event


def test_emit_event_noop() -> None:
    emit_event("test_event", x=1)
