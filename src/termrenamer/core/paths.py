"""The keys paths are compared and claimed by, and where a queued Source is on disk."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path


def path_key(path: Path) -> str:
    """A path's key: its folder resolved, then its own name, case folded.

    The path's own name is not followed, so a symbolic link keys as itself and
    never stands in for its target. Two paths with the same key are the same
    file or folder, whatever the letter case; sorting by the key gives
    source-path order.
    """
    return str(path.parent.resolve() / path.name).casefold()


def claim_key(path: Path) -> str:
    """The key a planned name is claimed by, worked out from the path as text; no disk is
    read.

    The text is decomposed (NFD), upper-cased and case folded, then composed (NFC).
    Decomposing first puts the combining marks in their canonical order before folding,
    as Unicode's canonical caseless match does: folding turns U+0345 into a base iota,
    so ``α\u0345\u0300`` and ``α\u0300\u0345``, one name on APFS, would otherwise fold
    apart. Upper-casing first is how Windows compares names, which takes dotless ``ı``
    for ``I`` and ``i``; case folding alone keeps it apart. Composing again gives one
    text for the canonically equal results of folding.

    So every name a filesystem may take for one name (``Café.jpg``, ``café.jpg`` and the
    decomposed ``café.jpg``) has one key. It is strict on purpose: two names a
    case-sensitive filesystem would keep apart get a number, which is harmless. It
    compares names being claimed at a new place, never sources: a source is told apart
    by its recorded path as text.
    """
    decomposed = unicodedata.normalize("NFD", str(path))
    return unicodedata.normalize("NFC", decomposed.upper().casefold())


def source_place(path: Path) -> Path:
    """Where the queued Source ``path`` is on disk, spelled as its folders list it.

    A folder, or a link or junction to one, is resolved: the person queued the folder it
    reaches. Anything else keeps its own name in its resolved folder, so a symbolic link
    to a video is the link itself, never its target. Reads the disk (:func:`as_listed`).
    """
    expanded = path.expanduser()
    if expanded.name in ("", ".", "..") or expanded.is_dir():
        return as_listed(expanded.resolve())
    return as_listed(expanded.parent.resolve() / expanded.name)


def as_listed(path: Path) -> Path:
    """The absolute ``path`` with each part spelled as the folder above it lists it.

    A part the listing holds exactly as written is kept. Otherwise it takes the listed
    name with its :func:`claim_key` that is the same directory entry (links not
    followed): ``Show Name`` for ``show name`` on a disk that ignores letter case, or the
    Unicode form the disk keeps. A part not found that way, or in a folder that cannot be
    listed, is kept as written with every part after it. So the same file reached under
    two spellings has one path as text, and two files whose names differ only in letter
    case on a disk that tells them apart keep theirs. A build calls it; a derive never
    does.
    """
    spelled = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    for i, part in enumerate(parts):
        listed = _listed_name(spelled, part)
        if listed is None:
            return spelled.joinpath(*parts[i:])
        spelled = spelled / listed
    return spelled


def _listed_name(folder: Path, name: str) -> str | None:
    """How ``folder`` lists the entry ``name`` reaches, or ``None`` when it is not found."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    if name in names:
        return name
    try:
        wanted = os.lstat(folder / name)
    except OSError:
        return None
    key = claim_key(Path(name))
    for listed in sorted(n for n in names if claim_key(Path(n)) == key):
        try:
            if os.path.samestat(os.lstat(folder / listed), wanted):
                return listed
        except OSError:
            continue
    return None
