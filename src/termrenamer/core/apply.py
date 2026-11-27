"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import errno
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from termrenamer.core.models import (
    ApplyOutcome,
    ApplyResult,
    ApplyStatus,
    EntryStatus,
    Plan,
    PlanEntry,
    PlanFingerprint,
    Straggler,
)
from termrenamer.core.moving import (
    Changes,
    NotAsRecorded,
    NowALink,
    folders_between,
    is_folder,
    is_link,
    leave_folder,
    move_no_replace,
)
from termrenamer.core.paths import claim_key
from termrenamer.core.planning import fingerprint
from termrenamer.util.errors import ValidationError

_LOG = logging.getLogger(__name__)

_TAKEN = "destination exists at apply time"
_STALE = "stale: source changed since plan"
_STOPPED = "not applied: Apply stopped after an unexpected error"


def _stale(exc: NotAsRecorded) -> str:
    """The reason for a source that is not as the Plan recorded it."""
    if exc.errno == errno.EISDIR:
        return "stale: the Plan listed a file and a folder is there now"
    if exc.errno == errno.ENOTDIR:
        return "stale: the Plan listed a folder and a file is there now"
    return _STALE


@dataclass(frozen=True, slots=True)
class _Way:
    """The folders one move goes through that must be real folders at the last look
    before it: ``new_side`` each folder from below the Destination root (or, with none,
    the owning Source's folder) to the new name's folder, and ``real_folders`` those and
    each folder from the owning Source's folder to the source's folder. A folder the
    Plan found to be a link already is gone through as the Preview showed it, and the
    Destination root itself may be a link."""

    new_side: tuple[Path, ...]
    real_folders: tuple[Path, ...]


def _way(plan: Plan, root: Path, source: Path, dest: Path) -> _Way:
    linked = {str(folder) for folder in plan.linked_folders}
    below = plan.options.destination_root or root
    new_side = tuple(f for f in folders_between(below, dest.parent) if str(f) not in linked)
    old_side = (root, *folders_between(root, source.parent))
    return _Way(
        new_side=new_side,
        real_folders=(*new_side, *(f for f in old_side if str(f) not in linked)),
    )


def _move(
    source: Path,
    dest: Path,
    changes: Changes,
    way: _Way,
    *,
    expected: PlanFingerprint | None = None,
    folder: bool | None = None,
) -> tuple[ApplyStatus, str]:
    """Make ``dest``'s folder and move ``source`` there without replacing anything or
    going through a link on ``way``: Apply's one move, for entries and Stragglers alike.
    With ``expected``, the source must still have the size and modification time the
    Plan recorded; with ``folder``, it must still be of the kind the Plan listed."""
    try:
        changes.make_folders(dest.parent, real_folders=way.new_side)
    except NowALink as exc:
        return ApplyStatus.SKIP, exc.reason
    except OSError as exc:
        return ApplyStatus.FAIL, f"mkdir failed: {exc}"
    try:
        move_no_replace(
            source,
            dest,
            changes,
            expected=expected,
            folder=folder,
            real_folders=way.real_folders,
        )
    except FileExistsError:
        return ApplyStatus.SKIP, _TAKEN
    except NowALink as exc:
        return ApplyStatus.SKIP, exc.reason
    except NotAsRecorded as exc:
        return ApplyStatus.SKIP, _stale(exc)
    except OSError as exc:
        return ApplyStatus.FAIL, f"rename/move failed: {exc}"
    return ApplyStatus.RENAMED, "ok"


def _remove_empty_source_dirs(applied_source_parents: set[Path], changes: Changes) -> None:
    """Remove source directories that are empty after moves (deepest first).

    Never deletes non-empty directories or files. Failures are logged, not raised.
    When the working folder is a directory being removed or inside it, it moves to the
    parent first (same idea as anipyrenamer). Each folder removed is recorded in
    ``changes``.
    """
    for dir_path in sorted(applied_source_parents, key=lambda p: (-len(p.parts), claim_key(p))):
        try:
            if not is_folder(dir_path, os.lstat(dir_path)) or any(dir_path.iterdir()):
                continue
            leave_folder(dir_path)
            dir_path.rmdir()
        except OSError as exc:
            _LOG.warning("Skipping source directory cleanup for %s: %s", dir_path, exc)
            continue
        changes.folders_removed.append(dir_path)


def _unreadable(exc: OSError) -> tuple[ApplyStatus, str]:
    """The result of a source that could not be read: gone, or failing."""
    if isinstance(exc, FileNotFoundError):
        return ApplyStatus.SKIP, "stale: source missing"
    return ApplyStatus.FAIL, f"cannot read the source: {exc}"


def _apply_entry(entry: PlanEntry, plan: Plan, changes: Changes) -> ApplyResult:
    """Rename one entry after the checks; touch nothing when a check fails."""
    source = entry.source
    dest = entry.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if dest is None:
        return result(ApplyStatus.SKIP, entry.status.value)
    try:
        current_fp = fingerprint(source)
    except OSError as exc:
        return result(*_unreadable(exc))
    if (
        current_fp.size != entry.fingerprint.size
        or current_fp.mtime_ns != entry.fingerprint.mtime_ns
    ):
        return result(ApplyStatus.SKIP, _STALE)
    if entry.has_its_name:
        return result(ApplyStatus.UNCHANGED, "already has its name")
    way = _way(plan, entry.root, source, dest)
    return result(*_move(source, dest, changes, way, expected=entry.fingerprint))


def _apply_straggler(
    straggler: Straggler,
    plan: Plan,
    root_of: dict[str, Path],
    moved_out: set[str],
    changes: Changes,
) -> ApplyResult:
    """Move one Straggler to the path the Plan fixed, when an entry left its folder and it
    is still of the kind the Plan listed."""
    source, dest = straggler.source, straggler.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if str(source.parent) not in moved_out:
        return result(ApplyStatus.SKIP, "nothing moved out of its folder")
    try:
        st = os.lstat(source)
    except OSError as exc:
        return result(*_unreadable(exc))
    if straggler.is_folder and is_link(source, st):
        return result(ApplyStatus.SKIP, NowALink(source).reason)
    if is_folder(source, st) != straggler.is_folder:
        kind = errno.ENOTDIR if straggler.is_folder else errno.EISDIR
        return result(ApplyStatus.SKIP, _stale(NotAsRecorded(kind, "", str(source))))
    root = root_of.get(str(source.parent), source.parent)
    way = _way(plan, root, source, dest)
    return result(*_move(source, dest, changes, way, folder=straggler.is_folder))


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


def _left_out(entry: PlanEntry) -> ApplyResult:
    return ApplyResult(
        source=entry.source,
        destination=None,
        status=ApplyStatus.LEFT_OUT,
        reason=EntryStatus.LEFT_OUT.value,
    )


def apply_plan(plan: Plan, *, confirmed: bool) -> ApplyOutcome:
    """Execute a Plan exactly as previewed; no file or folder of a source folder that it
    does not list is moved (a folder Straggler moves with what it holds at Apply).

    Applies the entries that have a destination: ready, and name taken with a numbered
    name (Name taken set to ``suffix``). Reports every other entry (no match, not
    recognised, name taken under ``skip``) as skipped with its status as the reason,
    and each left out entry as left out; neither is touched.
    Each video is handled before the Sidecars, each in the Plan's order, and a Sidecar
    is applied only when its video was renamed or unchanged in this Apply. Then each
    Straggler the Plan lists is moved to the path the Plan fixed, when at least one
    entry from its folder moved to another folder in this Apply and the Straggler still
    exists and is of the kind the Plan listed. Last, the source folders those moves
    emptied are removed. No move replaces anything, and none goes through a folder on
    its way that is now a link (see :func:`~termrenamer.core.moving.move_no_replace`):
    a source that changed since planning, or a folder on its way that is now a link,
    is skipped with the reason.

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

    # The Plan's own order, read from no disk: videos first, then the Sidecars.
    ordered = [e for e in plan.entries if not e.is_sidecar] + [
        e for e in plan.entries if e.is_sidecar
    ]
    changes = Changes()
    results: list[ApplyResult] = []
    stragglers: list[ApplyResult] = []
    try:
        stopped = _apply_all(plan, ordered, changes, results, stragglers)
    except Exception as exc:
        # Outside any one item; whatever moved is in ``changes``.
        _LOG.error("Apply stopped by an unexpected error", exc_info=exc)
        stopped = True
    if stopped:
        for entry in ordered[len(results) :]:
            if entry.status is EntryStatus.LEFT_OUT:
                results.append(_left_out(entry))
            else:
                results.append(_skipped(entry.source, entry.destination, _STOPPED))
        for straggler in plan.stragglers[len(stragglers) :]:
            stragglers.append(_skipped(straggler.source, straggler.destination, _STOPPED))
    return ApplyOutcome(
        results=tuple(results),
        stragglers=tuple(stragglers),
        moves=tuple(changes.moves),
        folders_created=tuple(changes.folders_created),
        folders_removed=tuple(changes.folders_removed),
        files_left_behind=tuple(changes.files_left_behind),
    )


def _apply_all(
    plan: Plan,
    ordered: list[PlanEntry],
    changes: Changes,
    results: list[ApplyResult],
    stragglers: list[ApplyResult],
) -> bool:
    """Apply the entries in ``ordered``, then the Stragglers, then remove the emptied
    folders, appending one result per item; return whether an unexpected error stopped
    Apply, which leaves the items after it without a result."""
    emptied: set[Path] = set()
    moved_out: set[str] = set()
    applied_sources: set[Path] = set()
    root_of: dict[str, Path] = {}
    for entry in plan.entries:
        root_of.setdefault(str(entry.source.parent), entry.root)

    for entry in ordered:
        if entry.status is EntryStatus.LEFT_OUT:
            # Before every check: a left out file is reported as left out, not skipped.
            results.append(_left_out(entry))
            continue
        if entry.video is not None and entry.video not in applied_sources:
            # The Plan left it without a name (its video's status), or its video was
            # skipped or failed in this Apply.
            not_named = entry.destination is None
            reason = entry.status.value if not_named else "video not applied"
            results.append(_skipped(entry.source, entry.destination, reason))
            continue
        try:
            outcome = _apply_entry(entry, plan, changes)
        except Exception as exc:
            results.append(_stopped_by(entry.source, entry.destination, exc))
            return True
        results.append(outcome)
        if outcome.status in (ApplyStatus.RENAMED, ApplyStatus.UNCHANGED):
            applied_sources.add(entry.source)
        if outcome.status is not ApplyStatus.RENAMED or entry.destination is None:
            continue
        # As the Plan judged it: a source folder by its recorded path, "another folder"
        # by the claim key.
        if claim_key(entry.source.parent) != claim_key(entry.destination.parent):
            emptied.add(entry.source.parent)
            moved_out.add(str(entry.source.parent))

    for straggler in plan.stragglers:
        try:
            result = _apply_straggler(straggler, plan, root_of, moved_out, changes)
        except Exception as exc:
            stragglers.append(_stopped_by(straggler.source, straggler.destination, exc))
            return True
        stragglers.append(result)
        if result.status is ApplyStatus.RENAMED:
            emptied.add(straggler.source.parent)

    try:
        _remove_empty_source_dirs(emptied, changes)
    except Exception:
        # The outcome is returned whatever the clean-up does.
        _LOG.exception("Removing the emptied source folders stopped")
    return False


def _skipped(source: Path, dest: Path | None, reason: str) -> ApplyResult:
    return ApplyResult(source=source, destination=dest, status=ApplyStatus.SKIP, reason=reason)
