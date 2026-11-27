"""Recursive directory scan for media and sidecar files."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from termrenamer.core.models import FileKind, ScannedFile
from termrenamer.core.paths import source_order

_LOG = logging.getLogger(__name__)

_VIDEO_EXT = frozenset({".mkv", ".mp4", ".avi", ".webm", ".m4v"})
_SIDECAR_EXT = frozenset({".srt", ".nfo", ".sub", ".idx"})


def classify(suffix: str) -> FileKind | None:
    """Return a file's kind by its suffix: video, Sidecar, or ``None`` for any other file."""
    s = suffix.lower()
    if s in _VIDEO_EXT:
        return FileKind.VIDEO
    if s in _SIDECAR_EXT:
        return FileKind.SIDECAR
    return None


def scan(*, root: Path) -> list[ScannedFile]:
    """Recursively discover video and known sidecar files under the folder ``root``.

    Non-media files (e.g. ``.txt``) are omitted. A symbolic link or a junction is never
    entered, even when it leads to a folder of videos; a symbolic link to a file is found
    as itself. Each path is ``root`` joined with the names as the folders list them. A
    folder that cannot be listed is passed over with a logged warning.
    """
    out: list[ScannedFile] = []
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as listing:
                children = list(listing)
        except OSError as exc:
            _LOG.warning("Cannot list %s: %s", folder, exc)
            continue
        for child in children:
            path = folder / child.name
            try:
                if child.is_dir(follow_symlinks=False) and not child.is_junction():
                    pending.append(path)
                    continue
                kind = classify(path.suffix)
                if kind is None or not child.is_file():
                    continue
            except OSError as exc:
                _LOG.warning("Cannot read %s: %s", path, exc)
                continue
            out.append(ScannedFile(path=path, root=root, kind=kind))
    return sorted(out, key=lambda sf: source_order(sf.path))
