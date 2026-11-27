"""Destination collision resolution without silent overwrite."""

from __future__ import annotations

import os
from pathlib import Path

from termrenamer.core.paths import claim_key
from termrenamer.core.policies import NameTakenPolicy


def is_case_only_rename(source: Path, dest: Path) -> bool:
    """Whether ``dest`` is ``source`` under another letter case or Unicode form of its
    name, in the same folder: the one move Apply makes as a plain rename.

    All of this must hold: the same parent folder as recorded, names that differ as text
    and have one :func:`~termrenamer.core.paths.claim_key`, one directory entry for both
    (``samestat``, links not followed), and a folder listing that holds the source's
    exact name and not the destination's. Two exact names in the listing are two entries,
    such as a separate hard link of the same file, so the destination is taken.
    """
    if source.parent != dest.parent or source.name == dest.name:
        return False
    if claim_key(Path(source.name)) != claim_key(Path(dest.name)):
        return False
    try:
        if not os.path.samestat(os.lstat(source), os.lstat(dest)):
            return False
        names = os.listdir(source.parent)
    except OSError:
        return False
    return source.name in names and dest.name not in names


def name_is_taken(path: Path, *, source: Path) -> bool:
    """Whether something other than ``source`` exists at ``path``.

    Symbolic links are not followed, so a broken link counts as something there. The
    source's own name, and a case-only rename (:func:`is_case_only_rename`), are not
    taken; a separate hard link of the source is.
    """
    if not path.exists(follow_symlinks=False):
        return False
    return str(path) != str(source) and not is_case_only_rename(source, path)


def _with_numeric_suffix(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem} ({n}){path.suffix}")


def allocate_destination(
    desired: Path,
    *,
    source: Path,
    occupied: set[str],
) -> Path:
    """Pick a destination path, using `` (1)``, `` (2)``, … before the extension if needed.

    ``occupied`` holds the :func:`~termrenamer.core.paths.claim_key` of each name already
    claimed, so two names that differ only in letter case or Unicode form are one path;
    the name picked is added to it. If ``desired`` is ``source`` under another letter
    case (a case-only rename), returns ``desired``.
    """
    if claim_key(desired) in occupied or name_is_taken(desired, source=source):
        return _first_free_suffix(desired, source, occupied)
    occupied.add(claim_key(desired))
    return desired


def _first_free_suffix(initial: Path, source: Path, occupied: set[str]) -> Path:
    n = 1
    while True:
        candidate = _with_numeric_suffix(initial, n)
        if claim_key(candidate) in occupied or name_is_taken(candidate, source=source):
            n += 1
            continue
        occupied.add(claim_key(candidate))
        return candidate


def claim_name(
    desired: Path,
    *,
    source: Path,
    occupied: set[str],
    policy: NameTakenPolicy,
) -> Path | None:
    """Claim ``desired`` for ``source``, or by ``policy`` a numbered name or none.

    A name is taken when :func:`name_is_taken` says so or an earlier entry has claimed it
    (its key is in ``occupied``). Under ``SUFFIX`` a taken name gives way to the
    first free numbered name; under ``SKIP`` nothing is claimed and ``None`` is returned.
    """
    if policy is NameTakenPolicy.SKIP and (
        claim_key(desired) in occupied or name_is_taken(desired, source=source)
    ):
        return None
    return allocate_destination(desired, source=source, occupied=occupied)
