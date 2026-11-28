"""What building a Plan reports while it runs, and how a build is cancelled.

:func:`termrenamer.core.planning.plan_queue` calls its listener with each event, in
order, on the thread the build runs on:

1. :class:`Scanned`: how many files need a lookup, the Titles by name and the not
   recognised files, before the first lookup;
2. for each Title, :class:`TitleLookupStarted`, then :class:`TitleLookedUp` (found or
   not found), then one :class:`FileLookedUp` for each of its files (matched or
   unmatched);
3. :class:`BuildFinished`, once every lookup is done.

A cached answer is reported the same way as a network one. A listener ignores an
event type it does not know. An exception a listener raises stops the build, and no
Plan is returned.

The build checks its :class:`CancelSignal` before each lookup. A cancelled build
reports no :class:`BuildFinished` and returns no Plan; a lookup already under way
finishes first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from termrenamer.core.models import Candidate


@dataclass(frozen=True, slots=True)
class ScannedTitle:
    """A Title as the build groups its files before lookup.

    ``name`` is the title hint read from the file names, ``year`` the year hint
    (Film), and ``videos`` how many of the queued videos belong to it.
    """

    name: str
    year: int | None
    videos: int


@dataclass(frozen=True, slots=True)
class Scanned:
    """The queue is read: what the build is about to look up.

    ``files`` is how many files need a lookup (every recognised video), the total that
    each :class:`FileLookedUp` counts towards. ``titles`` are in lookup order.
    ``not_recognised`` are the videos whose names could not be read; they get no lookup.
    """

    files: int
    titles: tuple[ScannedTitle, ...]
    not_recognised: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class TitleLookupStarted:
    """A Title's search is about to go to the Provider (or its cache)."""

    name: str
    year: int | None


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


@dataclass(frozen=True, slots=True)
class FileLookedUp:
    """One video's lookup finished: ``matched``, or not (its Title or episode not found).

    In Film Mode a video's lookup is its Title's search; in TV Mode it is the episode
    lookup that follows a found search. A video of a Title not found is unmatched.
    """

    path: Path
    matched: bool


@dataclass(frozen=True, slots=True)
class BuildFinished:
    """Every lookup is done; the Plan follows."""


PlanEvent = Scanned | TitleLookupStarted | TitleLookedUp | FileLookedUp | BuildFinished
"""Every event a build reports."""

PlanListener = Callable[[PlanEvent], None]
"""Called with each event of a build, in order."""


class CancelSignal(Protocol):
    """Set by another thread to cancel a build; :class:`threading.Event` is one."""

    def is_set(self) -> bool: ...
