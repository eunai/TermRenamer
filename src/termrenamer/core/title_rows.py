"""The rows of a Plan's Title list: one per Title, and one per not recognised video.

A Title's status word is the first that applies: no match (the Title has no Match, or
any of its files has the status no match), left out (every file is left out), name
taken (any file), ready. A not recognised video's row says not recognised, or left out
when the person left it out. Counts count videos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from termrenamer.core.models import (
    ApplyOutcome,
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
    """What a Plan holds, counted in videos (Sidecars are not counted), and its Stragglers.

    ``to_rename`` counts the videos Apply will rename: ready or name taken, with a
    destination that is not where the video already is. A video that already has its
    name is not counted as renamed. The other counts count videos by status, except
    ``stragglers``: the Stragglers the Plan lists, which Apply merges.
    """

    titles: int
    videos: int
    to_rename: int
    ready: int
    name_taken: int
    no_match: int
    not_recognised: int
    left_out: int
    stragglers: int

    @classmethod
    def of(cls, plan: Plan) -> PlanCounts:
        videos = plan.videos
        return cls(
            titles=len(plan.titles),
            videos=len(videos),
            to_rename=sum(
                1
                for v in videos
                if v.status in _RENAMED and v.destination is not None and not v.has_its_name
            ),
            ready=sum(1 for v in videos if v.status is EntryStatus.READY),
            name_taken=sum(1 for v in videos if v.status is EntryStatus.NAME_TAKEN),
            no_match=sum(1 for v in videos if v.status is EntryStatus.NO_MATCH),
            not_recognised=sum(1 for v in videos if v.status is EntryStatus.NOT_RECOGNISED),
            left_out=sum(1 for v in videos if v.status is EntryStatus.LEFT_OUT),
            stragglers=len(plan.stragglers),
        )


@dataclass(frozen=True, slots=True)
class AppliedCounts:
    """How many videos Apply renamed, left unchanged (already named), skipped and failed,
    how many were left out (not counted as skipped), and how many Stragglers it merged,
    did not merge, and failed to merge."""

    renamed: int
    unchanged: int
    skipped: int
    failed: int
    left_out: int
    stragglers_merged: int
    stragglers_not_merged: int
    stragglers_failed: int

    @property
    def anything_failed(self) -> bool:
        """Whether a video or a Straggler failed."""
        return bool(self.failed or self.stragglers_failed)

    @classmethod
    def of(cls, plan: Plan, outcome: ApplyOutcome) -> AppliedCounts:
        videos = {entry.source for entry in plan.videos}
        statuses = [r.status for r in outcome.results if r.source in videos]
        return cls(
            renamed=statuses.count(ApplyStatus.RENAMED),
            unchanged=statuses.count(ApplyStatus.UNCHANGED),
            skipped=statuses.count(ApplyStatus.SKIP),
            failed=statuses.count(ApplyStatus.FAIL),
            left_out=statuses.count(ApplyStatus.LEFT_OUT),
            stragglers_merged=outcome.stragglers_merged,
            stragglers_not_merged=len(outcome.stragglers) - outcome.stragglers_merged,
            stragglers_failed=sum(1 for r in outcome.stragglers if r.status is ApplyStatus.FAIL),
        )


def title_status(title: Title, entries: Sequence[PlanEntry]) -> EntryStatus:
    """The status word of ``title``, whose files are ``entries``."""
    statuses = {entry.status for entry in entries}
    if title.match is None or EntryStatus.NO_MATCH in statuses:
        return EntryStatus.NO_MATCH
    if statuses == {EntryStatus.LEFT_OUT}:
        return EntryStatus.LEFT_OUT
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
                status=video.status,  # not recognised, or left out
                entries=(video, *sidecars),
            )
        )
    return tuple(rows)


def sidecars_skipped_alone(plan: Plan) -> tuple[PlanEntry, ...]:
    """The Sidecars Apply will skip while their videos move: a Sidecar whose own name is
    taken under Name taken ``skip``. A left out Sidecar is never one: its video is left
    out with it."""
    named = {entry.source for entry in plan.videos if entry.destination is not None}
    return tuple(
        entry for entry in plan.entries if entry.video in named and entry.destination is None
    )
