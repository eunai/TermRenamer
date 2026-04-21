"""Associate sidecar files with primary media by stem."""

from __future__ import annotations

from termrenamer.core.models import FileKind, ScannedFile


def partition_by_kind(files: list[ScannedFile]) -> tuple[list[ScannedFile], list[ScannedFile]]:
    """Split scanned files into videos and sidecars."""
    videos = [f for f in files if f.kind is FileKind.VIDEO]
    sidecars = [f for f in files if f.kind is FileKind.SIDECAR]
    return videos, sidecars


def find_primary_for_sidecar(sidecar: ScannedFile, videos: list[ScannedFile]) -> ScannedFile | None:
    """Return the video file sharing the same parent directory and stem, if any."""
    for video in videos:
        same_parent = video.path.parent == sidecar.path.parent
        same_stem = video.stem.casefold() == sidecar.stem.casefold()
        if same_parent and same_stem:
            return video
    return None
