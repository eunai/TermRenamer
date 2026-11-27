"""The path key that the queue, planning and Apply compare paths by."""

from __future__ import annotations

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
    """The key a planned name is claimed by: the path as text, case folded, then in
    Unicode's composed form (NFC); no disk is read.

    Two names a filesystem may take for one name (``Café.jpg``, ``café.jpg`` and the
    decomposed ``café.jpg``) have one key. It is strict on purpose: two names a
    case-sensitive filesystem would keep apart get a number, which is harmless.
    Planning and deriving claim names, and order and select Stragglers, by it, so
    deriving a Plan never reads a folder again.
    """
    return unicodedata.normalize("NFC", str(path).casefold())
