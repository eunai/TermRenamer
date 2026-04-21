"""Recursive directory scan for media and sidecar files."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import FileKind, ScannedFile

_VIDEO_EXT = frozenset({".mkv", ".mp4", ".avi", ".webm", ".m4v"})
_SIDECAR_EXT = frozenset({".srt", ".nfo", ".sub", ".idx"})


def _classify(suffix: str) -> FileKind | None:
    s = suffix.lower()
    if s in _VIDEO_EXT:
        return FileKind.VIDEO
    if s in _SIDECAR_EXT:
        return FileKind.SIDECAR
    return None


def scan(*, root: Path) -> list[ScannedFile]:
    """Recursively discover video and known sidecar files under ``root``.

    Non-media files (e.g. ``.txt``) are omitted. Paths are anchored to ``root``.
    """
    resolved_root = root.resolve()
    out: list[ScannedFile] = []
    for path in resolved_root.rglob("*"):
        if not path.is_file():
            continue
        kind = _classify(path.suffix)
        if kind is None:
            continue
        out.append(ScannedFile(path=path, root=resolved_root, kind=kind))
    return sorted(out, key=lambda sf: str(sf.path).casefold())
