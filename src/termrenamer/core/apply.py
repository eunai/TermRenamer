"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from termrenamer.core.collisions import name_is_taken
from termrenamer.core.models import (
    ApplyOutcome,
    ApplyResult,
    ApplyStatus,
    Move,
    Plan,
    PlanEntry,
    PlanFingerprint,
    Straggler,
)
from termrenamer.core.paths import path_key
from termrenamer.core.planning import fingerprint
from termrenamer.util.errors import ValidationError

_LOG = logging.getLogger(__name__)


@dataclass
class _Record:
    """What this Apply has done so far: the moves and the folders it made."""

    moves: list[Move] = field(default_factory=list)
    folders_created: list[Path] = field(default_factory=list)

    def make_folders(self, folder: Path) -> None:
        """Make ``folder`` and each missing folder above it, recording each one made."""
        missing: list[Path] = []
        current = folder
        while not current.exists(follow_symlinks=False) and current.parent != current:
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            try:
                path.mkdir()
            except FileExistsError:
                continue
            self.folders_created.append(path)

    def move(self, source: Path, dest: Path) -> None:
        """Move ``source`` to ``dest`` and record it with what is at its new place."""
        _rename_or_move(source, dest)
        self.moves.append(Move(source=source, destination=dest, fingerprint=_at_new_place(dest)))


def _at_new_place(path: Path) -> PlanFingerprint | None:
    """A moved file's size and modification time, links not followed; ``None`` for a
    folder."""
    st = os.lstat(path)
    if path.is_dir(follow_symlinks=False):
        return None
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)


def _remove_empty_source_dirs(applied_source_parents: set[Path]) -> list[Path]:
    """Remove source directories that are empty after moves (deepest first).

    Never deletes non-empty directories or files. Failures are logged, not raised.
    If the process cwd is inside a directory being removed, chdir to the parent first
    (same idea as anipyrenamer). Returns the folders removed, in the order removed.
    """
    removed: list[Path] = []
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
        removed.append(dir_path)
    return removed


def _apply_entry(entry: PlanEntry, record: _Record) -> ApplyResult:
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
        record.make_folders(dest.parent)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"mkdir failed: {exc}")
    try:
        record.move(source, dest)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"rename/move failed: {exc}")
    return result(ApplyStatus.RENAMED, "ok")


def _apply_straggler(straggler: Straggler, moved_out: set[str], record: _Record) -> ApplyResult:
    """Move one Straggler to the path the Plan fixed, when an entry left its folder."""
    source, dest = straggler.source, straggler.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if path_key(source.parent) not in moved_out:
        return result(ApplyStatus.SKIP, "nothing moved out of its folder")
    if not source.exists(follow_symlinks=False):
        return result(ApplyStatus.SKIP, "stale: source missing")
    if name_is_taken(dest, source=source):
        return result(ApplyStatus.SKIP, "destination exists at apply time")
    try:
        record.make_folders(dest.parent)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"mkdir failed: {exc}")
    try:
        record.move(source, dest)
    except OSError as exc:
        return result(ApplyStatus.FAIL, f"rename/move failed: {exc}")
    return result(ApplyStatus.RENAMED, "ok")


def apply_plan(plan: Plan, *, confirmed: bool) -> ApplyOutcome:
    """Execute a Plan exactly as previewed, and nothing it does not list.

    Applies the entries that have a destination: ready, and name taken with a numbered
    name (Name taken set to ``suffix``). Reports every other entry (no match, not
    recognised, name taken under ``skip``) as skipped with its status as the reason.
    Each video is handled before the Sidecars, and a Sidecar is applied only when its
    video was renamed or unchanged in this Apply. Then each Straggler the Plan lists is
    moved to the path the Plan fixed, when at least one entry from its folder moved to
    another folder in this Apply and the Straggler still exists. Last, the source folders
    those moves emptied are removed.

    Args:
        plan: The Plan the Preview showed.
        confirmed: Must be True or :class:`ValidationError` is raised.

    Returns:
        The outcome: each entry's and each Straggler's result, every move, and the
        folders made and removed.
    """
    if not confirmed:
        msg = "Apply refused: user confirmation is required before filesystem changes"
        raise ValidationError(msg)

    ordered = sorted(plan.entries, key=lambda e: (e.is_sidecar, path_key(e.source)))
    record = _Record()
    results: list[ApplyResult] = []
    emptied: set[Path] = set()
    moved_out: set[str] = set()
    applied_sources: set[Path] = set()

    for entry in ordered:
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
        outcome = _apply_entry(entry, record)
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
        result = _apply_straggler(straggler, moved_out, record)
        stragglers.append(result)
        if result.status is ApplyStatus.RENAMED:
            emptied.add(straggler.source.parent)

    removed = _remove_empty_source_dirs(emptied)

    return ApplyOutcome(
        results=tuple(results),
        stragglers=tuple(stragglers),
        moves=tuple(record.moves),
        folders_created=tuple(record.folders_created),
        folders_removed=tuple(removed),
    )


def _rename_or_move(source: Path, dest: Path) -> None:
    """Prefer ``Path.rename``; fall back to ``shutil.move`` for cross-device moves."""
    try:
        source.rename(dest)
    except OSError:
        shutil.move(str(source), str(dest))
