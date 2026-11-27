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


def is_companion_file(path: Path) -> bool:
    """Whether the file ``path`` is a companion file: one whose name starts with ``._``,
    as macOS writes beside a file on a drive that cannot hold extended attributes (exFAT,
    FAT32, some network shares). It is not the person's file: never a video, a Sidecar
    or a Straggler, and Apply and Undo never move, copy or remove it by name. What the
    system does with it when the file beside it moves is the system's own."""
    return path.name.startswith("._")


def classify(path: Path) -> FileKind | None:
    """Return the kind of the file ``path`` by its suffix: video, Sidecar, or ``None``
    for a companion file (:func:`is_companion_file`) and any other file."""
    if is_companion_file(path):
        return None
    s = path.suffix.lower()
    if s in _VIDEO_EXT:
        return FileKind.VIDEO
    if s in _SIDECAR_EXT:
        return FileKind.SIDECAR
    return None


def scan(*, root: Path) -> list[ScannedFile]:
    """Recursively discover video and known sidecar files under the folder ``root``.

    Non-media files (e.g. ``.txt``) and companion files (:func:`is_companion_file`) are
    omitted. A symbolic link or a junction is never entered, even when it leads to a
    folder of videos; a symbolic link to a file is found as itself. Each path is
    ``root`` joined with the names as the folders list them. A folder that cannot be
    listed is passed over with a logged warning.
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
                kind = classify(path)
                if kind is None or not child.is_file():
                    continue
            except OSError as exc:
                _LOG.warning("Cannot read %s: %s", path, exc)
                continue
            out.append(ScannedFile(path=path, root=root, kind=kind))
    return sorted(out, key=lambda sf: source_order(sf.path))
