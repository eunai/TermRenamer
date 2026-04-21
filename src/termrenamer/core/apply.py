"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    PlanEntryStatus,
    PlanFingerprint,
    RenamePlan,
)
from termrenamer.core.planning import planning_order_key
from termrenamer.util.errors import ValidationError

_LOG = logging.getLogger(__name__)


def _stat_fingerprint(path: Path) -> PlanFingerprint:
    st = path.stat()
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=int(st.st_mtime_ns))


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


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


def apply_plan(
    plan: RenamePlan,
    *,
    confirmed: bool,
) -> list[ApplyResult]:
    """Execute a frozen rename plan.

    Args:
        plan: Immutable plan from preview.
        confirmed: Must be True or :class:`ValidationError` is raised (FR-007).

    Returns:
        Per-operation results in deterministic source-path order.
    """
    if not confirmed:
        msg = "Apply refused: user confirmation is required before filesystem changes"
        raise ValidationError(msg)

    ordered = sorted(plan.entries, key=lambda e: planning_order_key(e))
    results: list[ApplyResult] = []
    applied_source_parents: set[Path] = set()

    for entry in ordered:
        source = entry.source
        dest = entry.destination

        if entry.status is PlanEntryStatus.UNMATCHED:
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.SKIP,
                    reason="unmatched: no metadata found",
                ),
            )
            continue

        if not source.exists():
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.SKIP,
                    reason="stale: source missing",
                ),
            )
            continue

        current_fp = _stat_fingerprint(source)
        if (
            current_fp.size != entry.fingerprint.size
            or current_fp.mtime_ns != entry.fingerprint.mtime_ns
        ):
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.SKIP,
                    reason="stale: source changed since plan",
                ),
            )
            continue

        if dest.exists() and not _same_file(source, dest):
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.SKIP,
                    reason="destination exists at apply time",
                ),
            )
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.FAIL,
                    reason=f"mkdir failed: {exc}",
                ),
            )
            continue

        src_parent = source.parent
        try:
            _rename_or_move(source, dest)
        except OSError as exc:
            results.append(
                ApplyResult(
                    source=source,
                    destination=dest,
                    status=ApplyStatus.FAIL,
                    reason=f"rename/move failed: {exc}",
                ),
            )
            continue

        results.append(
            ApplyResult(
                source=source,
                destination=dest,
                status=ApplyStatus.SUCCESS,
                reason="ok",
            ),
        )
        if src_parent != dest.parent:
            applied_source_parents.add(src_parent)

    _remove_empty_source_dirs(applied_source_parents)

    return results


def _rename_or_move(source: Path, dest: Path) -> None:
    """Prefer ``Path.rename``; fall back to ``shutil.move`` for cross-device moves."""
    try:
        source.rename(dest)
    except OSError:
        shutil.move(str(source), str(dest))
