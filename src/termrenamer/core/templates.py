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
    enable_folder_rename: bool = True,
    enable_season_folders: bool = True,
) -> Path:
    """Build default TV destination path.

    When ``enable_folder_rename`` is False, only the **file** name changes; the
    destination directory is the source file's parent (``dest_root`` is ignored).

    When ``enable_folder_rename`` is True, the show (and optional season) tree is
    built under ``dest_root`` when set, otherwise under ``root`` (scan root).

    When ``enable_season_folders`` is False (TV, folder rename on), the file is
    placed flat under the canonical show folder (no ``Season NN`` segment).
    """
    episode = parse.episodes[0]
    show = sanitize_path_segment(metadata.show_title)
    base = (
        f"{show} - S{parse.season:02d}E{episode:02d} - "
        f"{sanitize_path_segment(metadata.episode_title)}"
    )
    name = sanitize_filename(base + original_path.suffix.lower())

    if not enable_folder_rename:
        return original_path.parent / name

    target = dest_root if dest_root is not None else root
    if enable_season_folders:
        season_label = f"Season {parse.season:02d}"
        season_dir = target / show / season_label
        return season_dir / name
    return target / show / name


def format_film_destination(
    *,
    root: Path,
    metadata: MovieMetadata,
    original_path: Path,
    dest_root: Path | None = None,
    enable_folder_rename: bool = True,
) -> Path:
    """Build default film destination path (``Title (Year)/Title (Year).ext``).

    When ``enable_folder_rename`` is False, only the **file** name changes in the
    source directory; ``dest_root`` is ignored.
    """
    label = f"{metadata.title} ({metadata.year})"
    single_name = sanitize_filename(label + original_path.suffix.lower())

    if not enable_folder_rename:
        return original_path.parent / single_name

    target = dest_root if dest_root is not None else root
    folder = target / sanitize_path_segment(label)
    name = sanitize_filename(label + original_path.suffix.lower())
    return folder / name
