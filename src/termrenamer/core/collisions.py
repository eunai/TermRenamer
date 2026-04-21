"""Destination collision resolution without silent overwrite."""

from __future__ import annotations

from pathlib import Path


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


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

    if desired.exists():
        if _same_file(source, desired):
            occupied.add(desired)
            return desired
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
        if candidate.exists() and not _same_file(source, candidate):
            n += 1
            continue
        occupied.add(candidate)
        return candidate
