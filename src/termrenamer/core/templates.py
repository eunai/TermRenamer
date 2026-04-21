"""Default output templates (v1 fixed patterns)."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import EpisodeMetadata, MovieMetadata, ParseResult
from termrenamer.core.sanitize import sanitize_filename, sanitize_path_segment


def format_tv_destination(
    *,
    root: Path,
    parse: ParseResult,
    metadata: EpisodeMetadata,
    original_path: Path,
    dest_root: Path | None = None,
) -> Path:
    """Build default TV destination path under ``root`` or optional ``dest_root``.

    When ``dest_root`` is set, the show/season tree is built under that folder instead of
    ``root`` (scan still uses ``root``). When ``None``, behavior matches pre-destination-root
    releases (paths under ``root``).

    Future (P4): when ``dest_root`` is ``None``, detect when the source file already lives in a
    folder named for the show and avoid redundant nesting.
    """
    target = dest_root if dest_root is not None else root
    show = sanitize_path_segment(metadata.show_title)
    season_label = f"Season {parse.season:02d}"
    season_dir = target / show / season_label
    episode = parse.episodes[0]
    base = (
        f"{show} - S{parse.season:02d}E{episode:02d} - "
        f"{sanitize_path_segment(metadata.episode_title)}"
    )
    name = sanitize_filename(base + original_path.suffix.lower())
    return season_dir / name


def format_film_destination(
    *,
    root: Path,
    metadata: MovieMetadata,
    original_path: Path,
    dest_root: Path | None = None,
) -> Path:
    """Build default film destination path (``Title (Year)/Title (Year).ext``).

    When ``dest_root`` is set, the folder/file is created under that root instead of ``root``.
    When ``None``, behavior matches earlier releases.

    Future (P4): when ``dest_root`` is ``None``, detect when the source file already lives in a
    folder named for the movie and avoid redundant sub-folders.
    """
    target = dest_root if dest_root is not None else root
    label = f"{metadata.title} ({metadata.year})"
    folder = target / sanitize_path_segment(label)
    name = sanitize_filename(label + original_path.suffix.lower())
    return folder / name
