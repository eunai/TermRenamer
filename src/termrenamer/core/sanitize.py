"""Sanitize path components for Windows and cross-platform safety."""

from __future__ import annotations

import re
from pathlib import Path

_WIN_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    },
)


def sanitize_path_segment(segment: str) -> str:
    """Sanitize one path segment (folder or file base name without path separators)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", segment)
    cleaned = cleaned.rstrip(" .") or "_"
    if cleaned.upper() in _WIN_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def sanitize_filename(name: str) -> str:
    """Sanitize a file name including extension."""
    path = Path(name)
    stem = sanitize_path_segment(path.stem)
    ext = path.suffix.lower()
    return stem + ext
