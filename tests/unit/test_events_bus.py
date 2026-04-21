"""Activity event bus and Activity feed formatting."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from termrenamer.observability.events import (
    ActivityEvent,
    ActivityEventBus,
    ActivityEventKind,
)
from termrenamer.tui.widgets.activity_pane import format_activity_markup, format_activity_timestamp


def test_bus_subscribe_emit_unsubscribe() -> None:
    bus = ActivityEventBus()
    seen: list[ActivityEvent] = []

    def cb(ev: ActivityEvent) -> None:
        seen.append(ev)

    unsub = bus.subscribe(cb)
    ev = ActivityEvent(
        kind=ActivityEventKind.SHOW_FOUND,
        timestamp=datetime(2026, 4, 17, 9, 5, 3),
        payload={"title": "Test Show"},
    )
    bus.emit(ev)
    assert len(seen) == 1 and seen[0].kind is ActivityEventKind.SHOW_FOUND

    unsub()
    bus.emit(ev)
    assert len(seen) == 1


def test_activity_event_is_frozen() -> None:
    ev = ActivityEvent(
        kind=ActivityEventKind.FILM_FOUND,
        timestamp=datetime.now(),
        payload={"title": "X", "year": "2020"},
    )
    with pytest.raises(FrozenInstanceError):
        ev.kind = ActivityEventKind.SHOW_FOUND  # type: ignore[misc]


def test_bus_exception_in_subscriber_does_not_break_other_subscribers() -> None:
    bus = ActivityEventBus()
    ok: list[str] = []

    def bad(_: ActivityEvent) -> None:
        raise RuntimeError("boom")

    def good(_: ActivityEvent) -> None:
        ok.append("ok")

    bus.subscribe(bad)
    bus.subscribe(good)
    ev = ActivityEvent(
        kind=ActivityEventKind.SHOW_FOUND,
        timestamp=datetime.now(),
        payload={"title": "S"},
    )
    bus.emit(ev)
    assert ok == ["ok"]


def test_format_activity_timestamp() -> None:
    dt = datetime(2026, 4, 17, 9, 5, 3)
    assert format_activity_timestamp(dt) == "2026-04-17 09:05:03"


def test_format_show_found() -> None:
    ev = ActivityEvent(
        kind=ActivityEventKind.SHOW_FOUND,
        timestamp=datetime(2026, 4, 17, 9, 5, 3),
        payload={"title": "Agatha All Along"},
    )
    line = format_activity_markup(ev)
    assert "2026-04-17 09:05:03" in line
    assert "Success." in line
    assert "Show found: Agatha All Along" in line


def test_format_episode_found() -> None:
    ev = ActivityEvent(
        kind=ActivityEventKind.EPISODE_FOUND,
        timestamp=datetime(2026, 4, 17, 9, 5, 3),
        payload={
            "show": "X",
            "season": "01",
            "episode": "07",
            "title": "Death's Hand in Mine",
        },
    )
    line = format_activity_markup(ev)
    assert "Episode found: S01E07 - Death's Hand in Mine" in line


def test_format_film_found() -> None:
    ev = ActivityEvent(
        kind=ActivityEventKind.FILM_FOUND,
        timestamp=datetime(2026, 4, 17, 9, 5, 3),
        payload={"title": "Show Name", "year": "2020"},
    )
    line = format_activity_markup(ev)
    assert "Film found: Show Name (2020)" in line
