"""What building a Plan reports while it runs: the progress listener and its events.

:func:`termrenamer.core.planning.plan_queue` calls its listener with each event, in
order, on the thread the build runs on. Today it reports one event, each Title looked
up; the scan result, each Title's lookup starting, each file's lookup and the end are
to be added beside it as more event types of :data:`PlanEvent`. A listener ignores an
event type it does not know. An exception a listener raises stops the build, and no
Plan is returned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from termrenamer.core.models import Candidate


@dataclass(frozen=True, slots=True)
class TitleLookedUp:
    """A Title's search finished: found, with its Match, or not found (``match`` is ``None``).

    ``name`` is the title hint read from the Title's file names, and ``year`` the year
    hint (Film), as the build groups them before lookup. Two Titles found with the same
    Match are one Title of the Plan.
    """

    name: str
    year: int | None
    match: Candidate | None


PlanEvent = TitleLookedUp
"""Every event a build reports."""

PlanListener = Callable[[PlanEvent], None]
"""Called with each event of a build, in order."""
