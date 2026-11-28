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


def claim_keys(path: Path) -> frozenset[str]:
    """The keys a claim of ``path`` holds in a set of claimed names.

    One is its :func:`~termrenamer.core.paths.claim_key`. The other is the claim key of
    the path its folder reaches on disk now, existing links and junctions followed and,
    on Windows, the folder's own spelling: so a name reached through a folder that points
    elsewhere, or under another spelling of an existing folder, is one claim with the
    name at the folder itself. This reads the disk only to test whether a name is taken,
    as :func:`name_is_taken` does; the name's own last part is not followed.
    """
    key = claim_key(path)
    try:
        reached = Path(os.path.realpath(path.parent)) / path.name
    except (OSError, ValueError):
        return frozenset((key,))
    return frozenset((key, claim_key(reached)))


def is_same_folder(folder: Path, target: Path) -> bool:
    """Whether the target folder ``target`` is ``folder`` itself.

    The same path as text is the same folder, and paths with two claim keys are two. When
    they differ only in letter case or Unicode form, the disk tells: ``target`` is
    ``folder`` when both are one directory entry (links not followed), as on a disk
    that ignores letter case; on a disk that tells them apart, or when ``target`` does
    not exist yet, they are two folders. A ``folder`` that is gone counts as ``target``
    itself, so it has no Stragglers to move. This tests whether the target folder's name
    is taken by ``folder`` itself; with :func:`name_is_taken` and :func:`claim_keys`, it
    is how a derive reads the disk.
    """
    if str(folder) == str(target):
        return True
    if claim_key(folder) != claim_key(target):
        return False
    if not os.path.lexists(folder):
        return True
    return _same_entry(folder, target)


def _same_entry(path: Path, other: Path) -> bool:
    """Whether ``path`` and ``other`` both exist and are one directory entry, links not
    followed."""
    try:
        return os.path.samestat(os.lstat(path), os.lstat(other))
    except OSError:
        return False


def _with_numeric_suffix(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem} ({n}){path.suffix}")


def _in_its_folder(desired: Path, source: Path) -> Path:
    """``desired``, spelled in ``source``'s folder as the Plan recorded it when its folder
    is that folder under another spelling (letter case or Unicode form) and the disk
    shows both as one directory entry, such as a Destination root typed ``library`` for
    a folder the disk lists as ``Library``: so a file that has its name keeps it, and a
    case-only rename stays one. A folder that is gone is never spelled in."""
    folder, wanted_folder = source.parent, desired.parent
    if (
        str(wanted_folder) != str(folder)
        and claim_key(wanted_folder) == claim_key(folder)
        and _same_entry(folder, wanted_folder)
    ):
        return folder / desired.name
    return desired


def _free_keys(path: Path, source: Path, occupied: set[str]) -> frozenset[str] | None:
    """The claim keys of ``path`` when no earlier claim holds it and nothing other than
    ``source`` is there, else ``None``: one look at the disk."""
    keys = claim_keys(path)
    if keys & occupied or name_is_taken(path, source=source):
        return None
    return keys


def allocate_destination(
    desired: Path,
    *,
    source: Path,
    occupied: set[str],
) -> Path:
    """Pick a destination path, using `` (1)``, `` (2)``, … before the extension if needed.

    ``occupied`` holds the :func:`claim_keys` of each name already claimed, so two names
    that differ only in letter case or Unicode form, or reach one folder through a link,
    are one path; the keys of the name picked are added to it. If ``desired`` is
    ``source`` under another letter case (a case-only rename), returns ``desired``.
    """
    claimed = claim_name(desired, source=source, occupied=occupied, policy=NameTakenPolicy.SUFFIX)
    assert claimed is not None
    return claimed


def claim_name(
    desired: Path,
    *,
    source: Path,
    occupied: set[str],
    policy: NameTakenPolicy,
) -> Path | None:
    """Claim ``desired`` for ``source``, or by ``policy`` a numbered name or none.

    A name is taken when :func:`name_is_taken` says so or an earlier entry has claimed it
    (one of its :func:`claim_keys` is in ``occupied``). Each name is looked at once: under
    ``SUFFIX`` a taken name gives way to the first free numbered name; under ``SKIP``
    nothing is claimed and ``None`` is returned, so a ``SKIP`` claim is ``desired`` or
    ``None`` whatever appears at the name meanwhile. A ``desired`` whose folder is the
    source's own folder under another spelling is claimed, and returned, spelled in the
    source's folder as recorded.
    """
    desired = _in_its_folder(desired, source)
    keys = _free_keys(desired, source, occupied)
    if keys is not None:
        occupied.update(keys)
        return desired
    if policy is NameTakenPolicy.SKIP:
        return None
    n = 1
    while True:
        candidate = _with_numeric_suffix(desired, n)
        keys = _free_keys(candidate, source, occupied)
        if keys is not None:
            occupied.update(keys)
            return candidate
        n += 1
