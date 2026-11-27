"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from termrenamer.core.models import (
    ApplyOutcome,
    ApplyResult,
    ApplyStatus,
    EntryStatus,
    Plan,
    PlanEntry,
    Straggler,
)
from termrenamer.core.moving import Changes, move_no_replace
from termrenamer.core.paths import path_key
from termrenamer.core.planning import fingerprint
from termrenamer.util.errors import ValidationError

_LOG = logging.getLogger(__name__)

_TAKEN = "destination exists at apply time"
_STOPPED = "not applied: Apply stopped after an unexpected error"


def _move(source: Path, dest: Path, changes: Changes) -> tuple[ApplyStatus, str]:
    """Make ``dest``'s folder and move ``source`` there without replacing anything:
    Apply's one move, for entries and Stragglers alike."""
    try:
        changes.make_folders(dest.parent)
    except OSError as exc:
        return ApplyStatus.FAIL, f"mkdir failed: {exc}"
    try:
        move_no_replace(source, dest, changes)
    except FileExistsError:
        return ApplyStatus.SKIP, _TAKEN
    except OSError as exc:
        return ApplyStatus.FAIL, f"rename/move failed: {exc}"
    return ApplyStatus.RENAMED, "ok"


def _remove_empty_source_dirs(applied_source_parents: set[Path], changes: Changes) -> None:
    """Remove source directories that are empty after moves (deepest first).

    Never deletes non-empty directories or files. Failures are logged, not raised.
    If the process cwd is inside a directory being removed, chdir to the parent first
    (same idea as anipyrenamer). Each folder removed is recorded in ``changes``.
    """
    cwd = Path.cwd().resolve()
    for dir_path in sorted(applied_source_parents, key=lambda p: (-len(p.parts), path_key(p))):
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
            continue
        changes.folders_removed.append(dir_path)


def _apply_entry(entry: PlanEntry, changes: Changes) -> ApplyResult:
    """Rename one entry after the checks; touch nothing when a check fails."""
    source = entry.source
    dest = entry.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if dest is None:
        return result(ApplyStatus.SKIP, entry.status.value)
    try:
        current_fp = fingerprint(source)
    except FileNotFoundError:
        return result(ApplyStatus.SKIP, "stale: source missing")
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"cannot read the source: {exc}")
    if (
        current_fp.size != entry.fingerprint.size
        or current_fp.mtime_ns != entry.fingerprint.mtime_ns
    ):
        return result(ApplyStatus.SKIP, "stale: source changed since plan")
    if entry.has_its_name:
        return result(ApplyStatus.UNCHANGED, "already has its name")
    return result(*_move(source, dest, changes))


def _apply_straggler(straggler: Straggler, moved_out: set[str], changes: Changes) -> ApplyResult:
    """Move one Straggler to the path the Plan fixed, when an entry left its folder."""
    source, dest = straggler.source, straggler.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if path_key(source.parent) not in moved_out:
        return result(ApplyStatus.SKIP, "nothing moved out of its folder")
    try:
        os.lstat(source)
    except FileNotFoundError:
        return result(ApplyStatus.SKIP, "stale: source missing")
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"cannot read the source: {exc}")
    return result(*_move(source, dest, changes))


def _stopped_by(source: Path, dest: Path | None, exc: Exception) -> ApplyResult:
    """The result of the item an unexpected error stopped Apply at; the error is logged
    with its traceback."""
    _LOG.error("Apply stopped at %s by an unexpected error", source, exc_info=exc)
    return ApplyResult(
        source=source,
        destination=dest,
        status=ApplyStatus.FAIL,
        reason=f"unexpected error: {exc!r}",
    )


def apply_plan(plan: Plan, *, confirmed: bool) -> ApplyOutcome:
    """Execute a Plan exactly as previewed, and nothing it does not list.

    Applies the entries that have a destination: ready, and name taken with a numbered
    name (Name taken set to ``suffix``). Reports every other entry (no match, not
    recognised, name taken under ``skip``) as skipped with its status as the reason,
    and each left out entry as left out; neither is touched.
    Each video is handled before the Sidecars, and a Sidecar is applied only when its
    video was renamed or unchanged in this Apply. Then each Straggler the Plan lists is
    moved to the path the Plan fixed, when at least one entry from its folder moved to
    another folder in this Apply and the Straggler still exists. Last, the source folders
    those moves emptied are removed. No move replaces anything (see
    :func:`~termrenamer.core.moving.move_no_replace`).

    An error reading or moving a file becomes that item's result. Any other error is
    logged with its traceback and fails its item, and Apply stops: every item after it
    is skipped as not applied, no folder is removed, and the outcome so far is returned.

    Args:
        plan: The Plan the Preview showed.
        confirmed: Must be True or :class:`ValidationError` is raised.

    Returns:
        The outcome: each entry's and each Straggler's result, every move, the
        folders made and removed, and any file left behind.
    """
    if not confirmed:
        msg = "Apply refused: user confirmation is required before filesystem changes"
        raise ValidationError(msg)

    ordered = sorted(plan.entries, key=lambda e: (e.is_sidecar, path_key(e.source)))
    changes = Changes()
    results: list[ApplyResult] = []
    emptied: set[Path] = set()
    moved_out: set[str] = set()
    applied_sources: set[Path] = set()
    stopped = False

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
        if stopped:
            results.append(_skipped(entry.source, entry.destination, _STOPPED))
            continue
        if entry.video is not None and entry.video not in applied_sources:
            # The Plan left it without a name (its video's status), or its video was
            # skipped or failed in this Apply.
            not_named = entry.destination is None
            reason = entry.status.value if not_named else "video not applied"
            results.append(_skipped(entry.source, entry.destination, reason))
            continue
        try:
            outcome = _apply_entry(entry, changes)
        except Exception as exc:
            outcome, stopped = _stopped_by(entry.source, entry.destination, exc), True
        results.append(outcome)
        if outcome.status in (ApplyStatus.RENAMED, ApplyStatus.UNCHANGED):
            applied_sources.add(entry.source)
        if outcome.status is not ApplyStatus.RENAMED or entry.destination is None:
            continue
        if path_key(entry.source.parent) != path_key(entry.destination.parent):
            emptied.add(entry.source.parent)
            moved_out.add(path_key(entry.source.parent))

    stragglers = []
    for straggler in plan.stragglers:
        if stopped:
            stragglers.append(_skipped(straggler.source, straggler.destination, _STOPPED))
            continue
        try:
            result = _apply_straggler(straggler, moved_out, changes)
        except Exception as exc:
            result, stopped = _stopped_by(straggler.source, straggler.destination, exc), True
        stragglers.append(result)
        if result.status is ApplyStatus.RENAMED:
            emptied.add(straggler.source.parent)

    if not stopped:
        _remove_empty_source_dirs(emptied, changes)

    return ApplyOutcome(
        results=tuple(results),
        stragglers=tuple(stragglers),
        moves=tuple(changes.moves),
        folders_created=tuple(changes.folders_created),
        folders_removed=tuple(changes.folders_removed),
        files_left_behind=tuple(changes.files_left_behind),
    )


def _skipped(source: Path, dest: Path | None, reason: str) -> ApplyResult:
    return ApplyResult(source=source, destination=dest, status=ApplyStatus.SKIP, reason=reason)
