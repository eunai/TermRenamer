"""Build deterministic rename plans without touching the filesystem (except stat)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.collisions import allocate_destination
from termrenamer.core.match import fetch_episode_metadata, fetch_film_metadata
from termrenamer.core.models import (
    PlanEntryStatus,
    PlanFingerprint,
    RenamePlan,
    RenamePlanEntry,
    ScanMode,
)
from termrenamer.core.parse import parse_filename, parse_film_filename
from termrenamer.core.scan import scan
from termrenamer.core.sidecars import find_primary_for_sidecar, partition_by_kind
from termrenamer.core.templates import format_film_destination, format_tv_destination
from termrenamer.observability.events import ActivityEvent, ActivityEventKind, default_bus
from termrenamer.util.errors import ParseError, ProviderError

_LOG = logging.getLogger(__name__)

_UNMATCHED_FILM_DEST_LABEL = "Movie not found."
_UNMATCHED_TV_DEST_LABEL = "Episode not found."


def _emit_activity(kind: ActivityEventKind, payload: dict[str, str]) -> None:
    """Publish a planning-time activity event (same process as stdlib log calls)."""

    default_bus().emit(
        ActivityEvent(kind=kind, timestamp=datetime.now(), payload=payload),
    )


def _fingerprint(path: Path) -> PlanFingerprint:
    st = path.stat()
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=int(st.st_mtime_ns))


def _normalized_source_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def build_rename_plan(
    *,
    root: Path,
    mode: ScanMode,
    provider: TvMetadataProvider | FilmMetadataProvider,
    film_dest_root: Path | None = None,
    tv_dest_root: Path | None = None,
) -> RenamePlan:
    """Scan ``root``, parse filenames, resolve metadata, and build a rename plan."""
    if mode is ScanMode.TV:
        if not isinstance(provider, TvMetadataProvider):
            msg = "TV mode requires a TvMetadataProvider"
            raise TypeError(msg)
        return _build_tv_plan(root=root, provider=provider, dest_root=tv_dest_root)
    if mode is ScanMode.FILM:
        if not isinstance(provider, FilmMetadataProvider):
            msg = "Film mode requires a FilmMetadataProvider"
            raise TypeError(msg)
        return _build_film_plan(root=root, provider=provider, dest_root=film_dest_root)
    msg = f"Unsupported scan mode: {mode!r}"
    raise ValueError(msg)


def _build_tv_plan(
    *,
    root: Path,
    provider: TvMetadataProvider,
    dest_root: Path | None = None,
) -> RenamePlan:
    files = scan(root=root)
    videos, sidecars = partition_by_kind(files)
    occupied: set[Path] = set()
    entries: list[RenamePlanEntry] = []
    dest_by_video: dict[Path, Path] = {}
    shows_seen: set[str] = set()

    for video in sorted(videos, key=lambda v: _normalized_source_key(v.path)):
        try:
            parsed = parse_filename(name=video.path.name, mode=ScanMode.TV)
        except ParseError as exc:
            _LOG.info("Skipping unparsed video %s: %s", video.path, exc)
            continue

        try:
            metadata = fetch_episode_metadata(provider, parsed)
        except ProviderError as exc:
            _LOG.info("No TV metadata for %s: %s", video.path, exc)
            group_id = str(video.path.resolve())
            entries.append(
                RenamePlanEntry(
                    source=video.path,
                    destination=video.path.parent / _UNMATCHED_TV_DEST_LABEL,
                    root=root.resolve(),
                    is_primary=True,
                    primary_source=None,
                    fingerprint=_fingerprint(video.path),
                    group_id=group_id,
                    status=PlanEntryStatus.UNMATCHED,
                ),
            )
            continue

        show_key = metadata.show_title.casefold()
        if show_key not in shows_seen:
            shows_seen.add(show_key)
            _emit_activity(ActivityEventKind.SHOW_FOUND, {"title": metadata.show_title})
        season_s = f"{parsed.season:02d}"
        episode_s = f"{parsed.primary_episode:02d}"
        _emit_activity(
            ActivityEventKind.EPISODE_FOUND,
            {
                "show": metadata.show_title,
                "season": season_s,
                "episode": episode_s,
                "title": metadata.episode_title,
            },
        )

        desired = format_tv_destination(
            root=root,
            parse=parsed,
            metadata=metadata,
            original_path=video.path,
            dest_root=dest_root,
        )
        final_dest = allocate_destination(desired, source=video.path, occupied=occupied)
        dest_by_video[video.path] = final_dest
        group_id = str(video.path.resolve())
        entries.append(
            RenamePlanEntry(
                source=video.path,
                destination=final_dest,
                root=root.resolve(),
                is_primary=True,
                primary_source=None,
                fingerprint=_fingerprint(video.path),
                group_id=group_id,
            ),
        )

    for sidecar in sorted(sidecars, key=lambda s: _normalized_source_key(s.path)):
        primary = find_primary_for_sidecar(sidecar, videos)
        if primary is None:
            _LOG.info("Skipping orphan sidecar %s", sidecar.path)
            continue
        primary_dest = dest_by_video.get(primary.path)
        if primary_dest is None:
            continue
        desired = primary_dest.with_suffix(sidecar.path.suffix.lower())
        final_dest = allocate_destination(desired, source=sidecar.path, occupied=occupied)
        group_id = str(primary.path.resolve())
        entries.append(
            RenamePlanEntry(
                source=sidecar.path,
                destination=final_dest,
                root=root.resolve(),
                is_primary=False,
                primary_source=primary.path,
                fingerprint=_fingerprint(sidecar.path),
                group_id=group_id,
            ),
        )

    ordered = tuple(sorted(entries, key=lambda e: _normalized_source_key(e.source)))
    return RenamePlan(entries=ordered, mode=ScanMode.TV)


def _build_film_plan(
    *,
    root: Path,
    provider: FilmMetadataProvider,
    dest_root: Path | None = None,
) -> RenamePlan:
    files = scan(root=root)
    videos, sidecars = partition_by_kind(files)
    occupied: set[Path] = set()
    entries: list[RenamePlanEntry] = []
    dest_by_video: dict[Path, Path] = {}

    for video in sorted(videos, key=lambda v: _normalized_source_key(v.path)):
        try:
            parsed = parse_film_filename(name=video.path.name)
        except ParseError as exc:
            _LOG.info("Skipping unparsed film %s: %s", video.path, exc)
            continue

        try:
            metadata = fetch_film_metadata(provider, parsed)
        except ProviderError as exc:
            _LOG.info("No film metadata for %s: %s", video.path, exc)
            group_id = str(video.path.resolve())
            entries.append(
                RenamePlanEntry(
                    source=video.path,
                    destination=video.path.parent / _UNMATCHED_FILM_DEST_LABEL,
                    root=root.resolve(),
                    is_primary=True,
                    primary_source=None,
                    fingerprint=_fingerprint(video.path),
                    group_id=group_id,
                    status=PlanEntryStatus.UNMATCHED,
                ),
            )
            continue

        _emit_activity(
            ActivityEventKind.FILM_FOUND,
            {"title": metadata.title, "year": str(metadata.year)},
        )

        desired = format_film_destination(
            root=root,
            metadata=metadata,
            original_path=video.path,
            dest_root=dest_root,
        )
        final_dest = allocate_destination(desired, source=video.path, occupied=occupied)
        dest_by_video[video.path] = final_dest
        group_id = str(video.path.resolve())
        entries.append(
            RenamePlanEntry(
                source=video.path,
                destination=final_dest,
                root=root.resolve(),
                is_primary=True,
                primary_source=None,
                fingerprint=_fingerprint(video.path),
                group_id=group_id,
            ),
        )

    for sidecar in sorted(sidecars, key=lambda s: _normalized_source_key(s.path)):
        primary = find_primary_for_sidecar(sidecar, videos)
        if primary is None:
            _LOG.info("Skipping orphan sidecar %s", sidecar.path)
            continue
        primary_dest = dest_by_video.get(primary.path)
        if primary_dest is None:
            continue
        desired = primary_dest.with_suffix(sidecar.path.suffix.lower())
        final_dest = allocate_destination(desired, source=sidecar.path, occupied=occupied)
        group_id = str(primary.path.resolve())
        entries.append(
            RenamePlanEntry(
                source=sidecar.path,
                destination=final_dest,
                root=root.resolve(),
                is_primary=False,
                primary_source=primary.path,
                fingerprint=_fingerprint(sidecar.path),
                group_id=group_id,
            ),
        )

    ordered = tuple(sorted(entries, key=lambda e: _normalized_source_key(e.source)))
    return RenamePlan(entries=ordered, mode=ScanMode.FILM)


def planning_order_key(entry: RenamePlanEntry) -> str:
    """Public ordering key for apply (normalized lexical source path)."""
    return _normalized_source_key(entry.source)


def filter_plan_to_queued_path(plan: RenamePlan, queued: Path) -> RenamePlan:
    """Keep entries tied to ``queued`` when planning scanned ``queued.parent``.

    A queued **file** is planned by scanning its parent directory; without this
    filter, siblings under the same parent would be included. Keeps the primary
    row for ``queued`` and any sidecars whose ``primary_source`` matches it.
    """
    try:
        q = queued.resolve()
    except OSError:
        return RenamePlan(entries=(), mode=plan.mode)
    kept: list[RenamePlanEntry] = []
    for entry in plan.entries:
        try:
            if entry.source.resolve() == q:
                kept.append(entry)
                continue
        except OSError:
            continue
        primary = entry.primary_source
        if primary is None:
            continue
        try:
            if primary.resolve() == q:
                kept.append(entry)
        except OSError:
            continue

    ordered = tuple(sorted(kept, key=planning_order_key))
    return RenamePlan(entries=ordered, mode=plan.mode)


def merge_rename_plans(subplans: Sequence[RenamePlan]) -> RenamePlan:
    """Combine per-root plans and resolve cross-root destination collisions.

    Each sub-plan is built against its own :func:`allocate_destination`
    occupied set. Merging re-applies allocating so two sources that map to the
    same library filename receive `` (1)`` / `` (2)`` suffixes without silent
    overwrite (spec §12.3).
    """
    if not subplans:
        msg = "merge_rename_plans requires at least one sub-plan"
        raise ValueError(msg)
    mode = subplans[0].mode
    for sub in subplans[1:]:
        if sub.mode is not mode:
            msg = "ScanMode mismatch when merging rename plans"
            raise ValueError(msg)

    merged_sources: list[RenamePlanEntry] = []
    for sub in subplans:
        merged_sources.extend(sub.entries)
    ordered = tuple(sorted(merged_sources, key=planning_order_key))
    occupied: set[Path] = set()
    rebuilt: list[RenamePlanEntry] = []
    for entry in ordered:
        final_dest = allocate_destination(
            entry.destination,
            source=entry.source,
            occupied=occupied,
        )
        if final_dest != entry.destination:
            rebuilt.append(replace(entry, destination=final_dest))
        else:
            rebuilt.append(entry)
    return RenamePlan(entries=tuple(rebuilt), mode=mode)
