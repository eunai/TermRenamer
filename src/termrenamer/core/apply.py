"""Apply rename plans to the filesystem with safety checks."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path

from termrenamer.core.collisions import name_is_taken
from termrenamer.core.models import (
    ApplyOutcome,
    ApplyResult,
    ApplyStatus,
    EntryStatus,
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
        """Move ``source`` to ``dest`` without replacing anything there, and record the
        move with the file's size and modification time at its new place.

        Once the move is made it is recorded: if the new place cannot be read, the
        values read at the old place just before the move stand in.
        """
        before = _file_fingerprint(source)
        _move_no_replace(source, dest)
        try:
            after = _file_fingerprint(dest)
        except OSError as exc:
            _LOG.warning("Cannot read %s after moving it there: %s", dest, exc)
            after = None if before is None else replace(before, path=dest)
        self.moves.append(Move(source=source, destination=dest, fingerprint=after))


def _file_fingerprint(path: Path) -> PlanFingerprint | None:
    """A file's size and modification time, links not followed; ``None`` for a folder."""
    st = os.lstat(path)
    if stat.S_ISDIR(st.st_mode):
        return None
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)


_NO_HARD_LINK = frozenset({errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP})
"""Why a hard link can fail other than a taken name: another filesystem, or one without
hard links (exFAT, many network shares)."""


def _move_no_replace(source: Path, dest: Path) -> None:
    """Move ``source`` to ``dest``; the move itself refuses to replace anything there.

    Raises :class:`FileExistsError` when something is at ``dest``, links not followed.

    - A case-only rename (``dest`` is ``source``'s own directory entry) is a plain rename.
    - On Windows, :func:`os.rename` never replaces a file or folder.
    - A file elsewhere is hard-linked at ``dest``, which fails when the name is taken,
      then unlinked from ``source``; a crash between the two leaves both names, never
      neither.
    - A folder elsewhere: ``dest`` is made first, which fails when the name is taken,
      and the folder is renamed onto that empty folder of its own.

    When the link or the rename cannot be made for another reason (another filesystem,
    a filesystem with no hard links), the move falls back to :func:`_rename_or_move`
    right after a :func:`name_is_taken` check. That path keeps a short window in which
    something that appears at ``dest`` could be replaced.
    """
    if dest.exists(follow_symlinks=False) and not name_is_taken(dest, source=source):
        os.rename(source, dest)
        return
    if os.name == "nt":
        try:
            os.rename(source, dest)
            return
        except FileExistsError:
            raise
        except OSError as exc:
            _LOG.info("Rename %s -> %s failed (%s); moving instead", source, dest, exc)
    elif source.is_dir(follow_symlinks=False):
        os.mkdir(dest)
        try:
            os.rename(source, dest)
            return
        except OSError as exc:
            with suppress(OSError):
                os.rmdir(dest)
            if exc.errno != errno.EXDEV:
                raise
    else:
        try:
            os.link(source, dest, follow_symlinks=False)
        except FileExistsError:
            raise
        except (OSError, NotImplementedError) as exc:
            if isinstance(exc, OSError) and exc.errno not in _NO_HARD_LINK:
                raise
            _LOG.info("Cannot hard-link %s -> %s (%s); moving instead", source, dest, exc)
        else:
            try:
                os.unlink(source)
            except OSError:
                with suppress(OSError):
                    os.unlink(dest)
                raise
            return
    if name_is_taken(dest, source=source):
        raise FileExistsError(errno.EEXIST, "destination exists", str(dest))
    _rename_or_move(source, dest)


def _move_checked(source: Path, dest: Path, record: _Record) -> tuple[ApplyStatus, str]:
    """Check ``dest`` is free, make its folder and move ``source`` there: Apply's one move,
    for entries and Stragglers alike."""
    if name_is_taken(dest, source=source):
        return ApplyStatus.SKIP, _TAKEN
    try:
        record.make_folders(dest.parent)
    except OSError as exc:
        return ApplyStatus.FAIL, f"mkdir failed: {exc}"
    try:
        record.move(source, dest)
    except FileExistsError:
        return ApplyStatus.SKIP, _TAKEN
    except OSError as exc:
        return ApplyStatus.FAIL, f"rename/move failed: {exc}"
    return ApplyStatus.RENAMED, "ok"


_TAKEN = "destination exists at apply time"


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
    return result(*_move_checked(source, dest, record))


def _apply_straggler(straggler: Straggler, moved_out: set[str], record: _Record) -> ApplyResult:
    """Move one Straggler to the path the Plan fixed, when an entry left its folder."""
    source, dest = straggler.source, straggler.destination

    def result(status: ApplyStatus, reason: str) -> ApplyResult:
        return ApplyResult(source=source, destination=dest, status=status, reason=reason)

    if path_key(source.parent) not in moved_out:
        return result(ApplyStatus.SKIP, "nothing moved out of its folder")
    if not source.exists(follow_symlinks=False):
        return result(ApplyStatus.SKIP, "stale: source missing")
    return result(*_move_checked(source, dest, record))


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
