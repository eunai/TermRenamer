"""Human-readable Activity feed (metadata matches) for the TUI Activity tab.

TODO: If planning moves to ``@work`` threads, schedule UI updates with
``app.call_from_thread`` from bus subscribers.

TODO: Per-line ellipsis + hover/focus full title needs a custom line widget;
``RichLog`` does not expose per-line tooltips.

TODO: Filtering by show or outcome kind — add predicates on the bus or a
filter bar that consults :class:`~termrenamer.observability.events.ActivityEvent`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from termrenamer.observability.events import ActivityEvent, ActivityEventKind, default_bus


def format_activity_timestamp(dt: datetime) -> str:
    """Format ``dt`` as ``YYYY-MM-DD HH:MM:SS`` (local, zero-padded, no microseconds)."""

    return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def format_activity_markup(event: ActivityEvent) -> str:
    """Rich markup line for one :class:`ActivityEvent` (timestamp + outcome + detail)."""

    ts = format_activity_timestamp(event.timestamp)
    dim_ts = f"[dim]{escape(ts)}[/dim]"
    success = "[success-kind]Success.[/success-kind]"
    p = event.payload

    if event.kind is ActivityEventKind.SHOW_FOUND:
        title = escape(p["title"])
        return f"{dim_ts}  {success} Show found: {title}"

    if event.kind is ActivityEventKind.EPISODE_FOUND:
        season = p["season"]
        episode = p["episode"]
        title = escape(p["title"])
        return f"{dim_ts}  {success} Episode found: S{season}E{episode} - {title}"

    if event.kind is ActivityEventKind.FILM_FOUND:
        title = escape(p["title"])
        year = escape(p["year"])
        return f"{dim_ts}  {success} Film found: {title} ({year})"

    # Future kinds: extend with failed-kind / skipped-kind when emitted.
    return f"{dim_ts}  {success} {escape(str(event.kind))}"


class _ActivityRichLog(RichLog):
    """RichLog that reports whether the vertical scroll is at the bottom (tail follow)."""

    def __init__(
        self,
        *,
        on_tail_follow: Callable[[bool], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._on_tail_follow = on_tail_follow

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if self._on_tail_follow is not None:
            self._on_tail_follow(self.is_vertical_scroll_end)


class ActivityPane(Vertical):
    """Subscribes to the activity bus and renders timestamped success lines."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._unsubscribe: Callable[[], None] | None = None
        self._follow_tail = True
        self._had_first_event = False

    def compose(self) -> ComposeResult:
        yield Static(
            "No activity yet. Build a plan to see results here.",
            id="activity-empty",
            classes="empty-state",
        )
        yield _ActivityRichLog(
            id="activity-log",
            markup=True,
            wrap=True,
            auto_scroll=True,
            on_tail_follow=self._on_tail_follow_changed,
        )

    def _on_tail_follow_changed(self, at_end: bool) -> None:
        self._follow_tail = at_end

    def on_mount(self) -> None:
        log = self.query_one("#activity-log", RichLog)
        empty = self.query_one("#activity-empty", Static)
        log.display = False
        empty.display = True
        self._unsubscribe = default_bus().subscribe(self._on_activity_event)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_activity_event(self, event: ActivityEvent) -> None:
        line = format_activity_markup(event)
        log = self.query_one("#activity-log", _ActivityRichLog)
        empty = self.query_one("#activity-empty", Static)
        if not self._had_first_event:
            self._had_first_event = True
            empty.display = False
            log.display = True
        log.write(line, scroll_end=self._follow_tail)
