"""Destination collision resolution without silent overwrite."""

from __future__ import annotations

import os
from pathlib import Path


def _same_entry(source: Path, path: Path) -> bool:
    """Whether ``path`` names the same directory entry as ``source``, links not followed."""
    try:
        return os.path.samestat(os.lstat(source), os.lstat(path))
    except OSError:
        return False


def name_is_taken(path: Path, *, source: Path) -> bool:
    """Whether something other than ``source`` exists at ``path``.

    Symbolic links are not followed, so a broken link counts as something there. A path
    that is the same file as ``source`` (a case-only rename) is not taken.
    """
    return path.exists(follow_symlinks=False) and not _same_entry(source, path)


def _with_numeric_suffix(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem} ({n}){path.suffix}")


def allocate_destination(
    desired: Path,
    *,
    source: Path,
    occupied: set[Path],
) -> Path:
    """Pick a destination path, using `` (1)``, `` (2)``, … before the extension if needed.

    Never uses ``os.replace`` for silent overwrite. If ``desired`` exists but is the same
    file as ``source`` (e.g. case-only rename), returns ``desired``.
    """
    if desired in occupied:
        return _first_free_suffix(desired, source, occupied)

    if name_is_taken(desired, source=source):
        return _first_free_suffix(desired, source, occupied)

    occupied.add(desired)
    return desired


def _first_free_suffix(initial: Path, source: Path, occupied: set[Path]) -> Path:
    n = 1
    while True:
        candidate = _with_numeric_suffix(initial, n)
        if candidate in occupied:
            n += 1
            continue
        if name_is_taken(candidate, source=source):
            n += 1
            continue
        occupied.add(candidate)
        return candidate
