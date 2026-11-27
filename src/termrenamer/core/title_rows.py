"""The rows of a Plan's Title list: one per Title, and one per not recognised video.

A Title's status word is the first that applies: no match (the Title has no Match, or
any of its files has the status no match), name taken (any file), ready. Counts count
videos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    EntryStatus,
    Plan,
    PlanEntry,
    Title,
    videos_of,
)

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
        return len(videos_of(self.entries))

    @property
    def files(self) -> tuple[PlanEntry, ...]:
        """The row's videos in the order its cells show them: by season and episode
        in TV Mode, then in the Plan's source-path order."""
        return tuple(sorted(videos_of(self.entries), key=lambda e: (e.season or 0, e.episode or 0)))

    def sidecars_of(self, video: PlanEntry) -> tuple[PlanEntry, ...]:
        """The Sidecars that belong to ``video``, one of the row's files."""
        return tuple(e for e in self.entries if e.video == video.source)


@dataclass(frozen=True, slots=True)
class PlanCounts:
    """What a Plan holds, counted in videos (Sidecars are not counted).

    ``to_rename`` counts the videos Apply will rename: ready or name taken, with a
    destination that is not where the video already is. A video that already has its
    name is not counted as renamed. The other counts count videos by status;
    ``left_out`` stays 0 until a video can be left out (#27).
    """

    titles: int
    videos: int
    to_rename: int
    ready: int
    name_taken: int
    no_match: int
    not_recognised: int
    left_out: int

    @classmethod
    def of(cls, plan: Plan) -> PlanCounts:
        videos = plan.videos
        return cls(
            titles=len(plan.titles),
            videos=len(videos),
            to_rename=sum(
                1 for v in videos if v.status in _RENAMED and v.destination not in (None, v.source)
            ),
            ready=sum(1 for v in videos if v.status is EntryStatus.READY),
            name_taken=sum(1 for v in videos if v.status is EntryStatus.NAME_TAKEN),
            no_match=sum(1 for v in videos if v.status is EntryStatus.NO_MATCH),
            not_recognised=sum(1 for v in videos if v.status is EntryStatus.NOT_RECOGNISED),
            left_out=0,
        )


@dataclass(frozen=True, slots=True)
class AppliedCounts:
    """How many videos Apply renamed, left unchanged (already named), skipped and failed."""

    renamed: int
    unchanged: int
    skipped: int
    failed: int

    @classmethod
    def of(cls, plan: Plan, results: Sequence[ApplyResult]) -> AppliedCounts:
        videos = {entry.source for entry in plan.videos}
        statuses = [r.status for r in results if r.source in videos]
        return cls(
            renamed=statuses.count(ApplyStatus.RENAMED),
            unchanged=statuses.count(ApplyStatus.UNCHANGED),
            skipped=statuses.count(ApplyStatus.SKIP),
            failed=statuses.count(ApplyStatus.FAIL),
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
    not_recognised = sorted(
        (e for e in plan.entries if e.title is None and not e.is_sidecar),
        key=lambda e: e.source.name.casefold(),
    )
    for video in not_recognised:
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
