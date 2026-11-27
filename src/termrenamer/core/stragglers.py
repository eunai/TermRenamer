"""List a Plan's Stragglers from its entries and the children its source folders had.

:func:`plan_stragglers` is the one rule (spec #16, section C). Building a Plan and
deriving one both call it; it never lists a folder, so a derived Plan lists Stragglers
from the children recorded when the first Plan was built. The disk is read only to
test whether a name is taken: each Straggler's wanted path is claimed as an entry's is
(:func:`~termrenamer.core.collisions.allocate_destination`), and a target folder whose
name differs from its source folder's only in letter case or Unicode form is tested for
being that folder (:func:`~termrenamer.core.collisions.is_same_folder`). A source
folder, an entry and a child are told apart by their recorded paths as text; names
being claimed and target folders are compared by
:func:`~termrenamer.core.paths.claim_key`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from termrenamer.core.collisions import allocate_destination, claim_keys, is_same_folder
from termrenamer.core.models import PlanEntry, PlanOptions, SourceFolder, Straggler
from termrenamer.core.paths import claim_key, source_order


def _folder_stays(folder: Path, sources: frozenset[str], target_keys: frozenset[str]) -> bool:
    """Whether a child folder is never a Straggler: it contains an entry of the Plan (by
    the recorded paths as text), or it is, contains or lies inside a target folder (a
    folder an entry of the Plan moves into), by claim key: a folder that may be a target
    folder under another spelling stays where it is."""
    inside = str(folder) + os.sep
    if any(source.startswith(inside) for source in sources):
        return True
    key = claim_key(folder)
    return any(
        t == key or t.startswith(key + os.sep) or key.startswith(t + os.sep) for t in target_keys
    )


def plan_stragglers(
    options: PlanOptions,
    entries: Iterable[PlanEntry],
    source_folders: Iterable[SourceFolder],
) -> tuple[Straggler, ...]:
    """The Stragglers of a Plan with ``options``, ``entries`` and ``source_folders``.

    With Folder rename off there are none. A source folder qualifies when at least one
    of its entries is applied to a different folder. Its Stragglers are its recorded
    child files that are not entries, and its recorded child folders that
    :func:`_folder_stays` does not keep. Each goes to the target folder that sorts
    first of those its folder's entries go to. After every applied entry has claimed
    its name, the Stragglers are numbered and claim theirs in source-path order, by the
    numbering rule whatever Name taken is set to, so no two share a path.
    """
    if not options.folder_rename:
        return ()
    entries = tuple(entries)
    applied = [e for e in entries if e.to_apply]
    claimed = {k for e in applied if e.destination is not None for k in claim_keys(e.destination)}
    sources = frozenset(str(e.source) for e in entries)
    # An entry that already has its name moves into no folder.
    moving = [e for e in applied if not e.has_its_name]
    target_keys = frozenset(claim_key(d.parent) for e in moving if (d := e.destination))

    # A source folder is told apart by its recorded path as text, so two folders whose
    # names differ only in letter case stay two; a target folder whose name differs from
    # it only in letter case or Unicode form is that folder when the disk says so.
    target_of: dict[str, Path] = {}
    for dest_folder, source_folder in sorted(
        {(d.parent, e.source.parent) for e in moving if (d := e.destination)},
        key=lambda pair: source_order(pair[0]),
    ):
        if not is_same_folder(source_folder, dest_folder):
            target_of.setdefault(str(source_folder), dest_folder)

    wanted: list[tuple[Path, Path]] = []
    for folder in source_folders:
        target = target_of.get(str(folder.path))
        if target is None:
            continue
        wanted.extend((f, target) for f in folder.files if str(f) not in sources)
        wanted.extend(
            (f, target) for f in folder.folders if not _folder_stays(f, sources, target_keys)
        )
    return tuple(
        Straggler(
            source=child,
            destination=allocate_destination(target / child.name, source=child, occupied=claimed),
        )
        for child, target in sorted(wanted, key=lambda pair: source_order(pair[0]))
    )
