"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from termrenamer.core.collisions import allocate_destination, name_is_taken
from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    EntryStatus,
    Plan,
    PlanEntry,
)
from termrenamer.core.paths import path_key
from termrenamer.core.planning import fingerprint
from termrenamer.util.errors import ValidationError

_LOG = logging.getLogger(__name__)


def _remove_empty_source_dirs(applied_source_parents: set[Path]) -> None:
    """Remove source directories that are empty after moves (deepest first).

    Never deletes non-empty directories or files. Failures are logged, not raised.
    If the process cwd is inside a directory being removed, chdir to the parent first
    (same idea as anipyrenamer).
    """
    cwd = Path.cwd().resolve()
    for dir_path in sorted(applied_source_parents, key=lambda p: len(p.parts), reverse=True):
        if not dir_path.exists() or not dir_path.is_dir():
            continue
        try:
            if any(dir_path.iterdir()):
                continue
        except OSError as exc:
            _LOG.warning("Skipping source directory cleanup for %s: %s", dir_path, exc)
            continue

        try:
            resolved_dir = dir_path.resolve()
        except OSError:
            resolved_dir = dir_path
        if resolved_dir == cwd:
            try:
                os.chdir(str(dir_path.parent))
                cwd = Path.cwd().resolve()
            except OSError as exc:
                _LOG.warning(
                    "Could not leave source directory %s before cleanup: %s",
                    dir_path,
                    exc,
                )
                continue

        try:
            dir_path.rmdir()
        except OSError as exc:
            _LOG.warning("Skipping source directory cleanup for %s: %s", dir_path, exc)


def _kept_in_place(child: Path, entry_keys: frozenset[str], target_keys: frozenset[str]) -> bool:
    """Whether the Straggler merge must leave ``child`` where it is.

    That is a file of the Plan or a folder holding one, and a folder that is,
    contains or lies inside a target folder (a folder an entry of the Plan moves into).
    """
    key = path_key(child)
    if any(k == key or k.startswith(key + os.sep) for k in entry_keys):
        return True
    return any(
        t == key or t.startswith(key + os.sep) or key.startswith(t + os.sep) for t in target_keys
    )


def _merge_stragglers(
    merge_pairs: set[tuple[Path, Path]],
    occupied: set[Path],
    entry_keys: frozenset[str],
    target_keys: frozenset[str],
) -> set[Path]:
    """After planned moves, move any remaining children into destination folders.

    Uses the same `` (1)`` / `` (2)`` collision policy as planning. What
    :func:`_kept_in_place` names is never moved this way. Log-only on failures.
    Returns old parents that may now be empty.
    """
    maybe_empty: set[Path] = set()
    for old_p, new_p in sorted(
        merge_pairs,
        key=lambda t: (path_key(t[0]), path_key(t[1])),
    ):
        if not old_p.exists() or not old_p.is_dir():
            continue
        try:
            children = sorted(old_p.iterdir(), key=lambda p: p.name.casefold())
        except OSError as exc:
            _LOG.warning("Cannot list %s for merge: %s", old_p, exc)
            continue
        children = [c for c in children if not _kept_in_place(c, entry_keys, target_keys)]
        if not children:
            continue
        try:
            new_p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _LOG.warning("Cannot create merge destination %s: %s", new_p, exc)
            continue
        for child in children:
            desired = new_p / child.name
            final = allocate_destination(desired, source=child, occupied=occupied)
            try:
                _rename_or_move(child, final)
            except OSError as exc:
                _LOG.warning("Merge move failed %s -> %s: %s", child, final, exc)
                continue
        maybe_empty.add(old_p)
    return maybe_empty


def _apply_entry(entry: PlanEntry) -> ApplyResult:
    """Rename one entry after the checks; touch nothing when a check fails."""
    source = entry.source
    dest = entry.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if dest is None:
        return result(ApplyStatus.SKIP, entry.status.value)
    if not source.exists():
        return result(ApplyStatus.SKIP, "stale: source missing")
    current_fp = fingerprint(source)
    if (
        current_fp.size != entry.fingerprint.size
        or current_fp.mtime_ns != entry.fingerprint.mtime_ns
    ):
        return result(ApplyStatus.SKIP, "stale: source changed since plan")
    if entry.has_its_name:
        return result(ApplyStatus.UNCHANGED, "already has its name")
    if name_is_taken(dest, source=source):
        return result(ApplyStatus.SKIP, "destination exists at apply time")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"mkdir failed: {exc}")
    try:
        _rename_or_move(source, dest)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"rename/move failed: {exc}")
    return result(ApplyStatus.RENAMED, "ok")


def apply_plan(plan: Plan, *, confirmed: bool) -> list[ApplyResult]:
    """Execute a Plan exactly as previewed.

    Applies the entries that have a destination: ready, and name taken with a numbered
    name (Name taken set to ``suffix``). Reports every other entry (no match, not
    recognised, name taken under ``skip``) as skipped with its status as the reason,
    and each left out entry as left out; neither is touched.
    Each video is handled before the Sidecars, and a Sidecar is applied only when its
    video was renamed or unchanged in this Apply. While the Plan was built with Folder
    rename on, the files left in a folder that a video moved out of are merged into the
    video's new folder, except files of the Plan.

    Args:
        plan: The Plan the Preview showed.
        confirmed: Must be True or :class:`ValidationError` is raised.

    Returns:
        One result per entry: videos in source-path order, then Sidecars.
    """
    if not confirmed:
        msg = "Apply refused: user confirmation is required before filesystem changes"
        raise ValidationError(msg)

    ordered = sorted(plan.entries, key=lambda e: (e.is_sidecar, path_key(e.source)))
    results: list[ApplyResult] = []
    applied_source_parents: set[Path] = set()
    merge_pairs: set[tuple[Path, Path]] = set()
    occupied: set[Path] = set()
    applied_sources: set[Path] = set()

    for entry in ordered:
        if entry.status is EntryStatus.LEFT_OUT:
            # Before every check: a left out file is reported as left out, not skipped.
            results.append(
                ApplyResult(
                    source=entry.source,
                    destination=None,
                    status=ApplyStatus.LEFT_OUT,
                    reason=EntryStatus.LEFT_OUT.value,
                ),
            )
            continue
        if entry.video is not None and entry.video not in applied_sources:
            # The Plan left it without a name (its video's status), or its video was
            # skipped or failed in this Apply.
            not_named = entry.destination is None
            reason = entry.status.value if not_named else "video not applied"
            results.append(
                ApplyResult(
                    source=entry.source,
                    destination=entry.destination,
                    status=ApplyStatus.SKIP,
                    reason=reason,
                ),
            )
            continue
        outcome = _apply_entry(entry)
        results.append(outcome)
        if outcome.status in (ApplyStatus.RENAMED, ApplyStatus.UNCHANGED):
            applied_sources.add(entry.source)
        if outcome.status is not ApplyStatus.RENAMED or entry.destination is None:
            continue
        dest = entry.destination
        occupied.add(dest)
        if entry.source.parent != dest.parent:
            applied_source_parents.add(entry.source.parent)
            if plan.options.folder_rename:
                merge_pairs.add((entry.source.parent, dest.parent))

    if merge_pairs:
        entry_keys = frozenset(path_key(e.source) for e in plan.entries)
        target_keys = frozenset(
            path_key(e.destination.parent) for e in plan.entries if e.destination
        )
        applied_source_parents |= _merge_stragglers(merge_pairs, occupied, entry_keys, target_keys)

    _remove_empty_source_dirs(applied_source_parents)

    return results


def _rename_or_move(source: Path, dest: Path) -> None:
    """Prefer ``Path.rename``; fall back to ``shutil.move`` for cross-device moves."""
    try:
        source.rename(dest)
    except OSError:
        shutil.move(str(source), str(dest))
