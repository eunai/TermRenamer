"""List a Plan's Stragglers from its entries and the children its source folders had.

:func:`plan_stragglers` is the one rule (spec #16, section C). Building a Plan and
deriving one both call it; it never lists a folder, so a derived Plan lists Stragglers
from the children recorded when the first Plan was built. It tests each Straggler's
wanted path on disk with :func:`~termrenamer.core.collisions.name_is_taken`, as the
planning test does, and reads no other path from the disk: a source folder is told
apart by its recorded path as text, and names, target folders and "another folder" are
compared by :func:`~termrenamer.core.paths.claim_key`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from termrenamer.core.collisions import allocate_destination
from termrenamer.core.models import PlanEntry, PlanOptions, SourceFolder, Straggler
from termrenamer.core.paths import claim_key


def _folder_stays(folder: Path, entry_keys: frozenset[str], target_keys: frozenset[str]) -> bool:
    """Whether a child folder is never a Straggler: it contains an entry of the Plan, or
    it is, contains or lies inside a target folder (a folder an entry of the Plan moves
    into)."""
    key = claim_key(folder)
    if any(k.startswith(key + os.sep) for k in entry_keys):
        return True
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
    claimed = {claim_key(e.destination) for e in applied if e.destination is not None}
    entry_keys = frozenset(claim_key(e.source) for e in entries)
    # An entry that already has its name moves into no folder.
    moving = [e for e in applied if not e.has_its_name]
    target_keys = frozenset(claim_key(d.parent) for e in moving if (d := e.destination))

    # A source folder is told apart by its recorded path as text, so two folders whose
    # names differ only in letter case stay two; "a different folder" is judged by the
    # claim key, so a move that may be into the same folder makes no Stragglers.
    target_of: dict[str, Path] = {}
    for dest_folder, source_folder in sorted(
        {(d.parent, e.source.parent) for e in moving if (d := e.destination)},
        key=lambda pair: (claim_key(pair[0]), str(pair[0])),
    ):
        if claim_key(dest_folder) != claim_key(source_folder):
            target_of.setdefault(str(source_folder), dest_folder)

    wanted: list[tuple[Path, Path]] = []
    for folder in source_folders:
        target = target_of.get(str(folder.path))
        if target is None:
            continue
        wanted.extend((f, target) for f in folder.files if claim_key(f) not in entry_keys)
        wanted.extend(
            (f, target) for f in folder.folders if not _folder_stays(f, entry_keys, target_keys)
        )
    return tuple(
        Straggler(
            source=child,
            destination=allocate_destination(target / child.name, source=child, occupied=claimed),
        )
        for child, target in sorted(wanted, key=lambda pair: (claim_key(pair[0]), str(pair[0])))
    )
