"""The rows of a Plan's Title list: one per Title, and one per not recognised video.

A Title's status word is the first that applies: no match (the Title has no Match, or
any of its files has the status no match), name taken (any file), ready. Counts count
videos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from termrenamer.core.models import EntryStatus, Plan, PlanEntry, Title

_RENAMED = frozenset({EntryStatus.READY, EntryStatus.NAME_TAKEN})


@dataclass(frozen=True, slots=True)
class TitleRow:
    """One row: a Title with its files, or a not recognised video (``title`` is ``None``).

    ``name`` is the Title's name, or the not recognised video's file name.
    """

    name: str
    title: Title | None
    status: EntryStatus
    entries: tuple[PlanEntry, ...]

    @property
    def videos(self) -> int:
        """How many of the row's files are videos."""
        return sum(1 for entry in self.entries if not entry.is_sidecar)


@dataclass(frozen=True, slots=True)
class PlanCounts:
    """What a Plan holds, counted in videos (Sidecars are not counted).

    ``to_rename`` counts the videos Apply will rename: ready or name taken, with a
    destination that is not where the video already is. A video that already has its
    name is not counted as renamed.
    """

    titles: int
    videos: int
    to_rename: int
    no_match: int
    not_recognised: int

    @classmethod
    def of(cls, plan: Plan) -> PlanCounts:
        videos = plan.videos
        return cls(
            titles=len(plan.titles),
            videos=len(videos),
            to_rename=sum(
                1 for v in videos if v.status in _RENAMED and v.destination not in (None, v.source)
            ),
            no_match=sum(1 for v in videos if v.status is EntryStatus.NO_MATCH),
            not_recognised=sum(1 for v in videos if v.status is EntryStatus.NOT_RECOGNISED),
        )


def title_status(title: Title, entries: Sequence[PlanEntry]) -> EntryStatus:
    """The status word of ``title``, whose files are ``entries``."""
    statuses = {entry.status for entry in entries}
    if title.match is None or EntryStatus.NO_MATCH in statuses:
        return EntryStatus.NO_MATCH
    if EntryStatus.NAME_TAKEN in statuses:
        return EntryStatus.NAME_TAKEN
    return EntryStatus.READY


def title_rows(plan: Plan) -> tuple[TitleRow, ...]:
    """The Titles in the Plan's order, then each not recognised video by file name."""
    rows = []
    for title in plan.titles:
        entries = tuple(e for e in plan.entries if e.title == title)
        rows.append(
            TitleRow(
                name=title.name,
                title=title,
                status=title_status(title, entries),
                entries=entries,
            )
        )
    unread = sorted(
        (e for e in plan.entries if e.title is None and not e.is_sidecar),
        key=lambda e: e.source.name.casefold(),
    )
    for video in unread:
        sidecars = tuple(e for e in plan.entries if e.video == video.source)
        rows.append(
            TitleRow(
                name=video.source.name,
                title=None,
                status=EntryStatus.NOT_RECOGNISED,
                entries=(video, *sidecars),
            )
        )
    return tuple(rows)
