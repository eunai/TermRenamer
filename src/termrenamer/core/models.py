"""Core data models for scan, parse, and rename planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class ScanMode(StrEnum):
    """User-selected library mode."""

    TV = "tv"
    FILM = "film"


PROVIDER_IDS: Mapping[ScanMode, tuple[str, ...]] = MappingProxyType(
    {ScanMode.TV: ("tmdb", "tvdb"), ScanMode.FILM: ("tmdb", "omdb")}
)
"""The Providers each Mode accepts, by id, in the order they are offered."""

PROVIDER_NAMES: Mapping[str, str] = MappingProxyType(
    {"tmdb": "TMDB", "tvdb": "TheTVDB", "omdb": "OMDb"}
)
"""Each Provider's name as people read it, by id."""


class FileKind(StrEnum):
    """Classification of a scanned path."""

    VIDEO = "video"
    SIDECAR = "sidecar"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A file discovered under a working root."""

    path: Path
    root: Path
    kind: FileKind

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Structured parse of a TV episode backup's filename."""

    show_hint: str
    season: int
    episodes: tuple[int, ...]

    @property
    def primary_episode(self) -> int:
        return self.episodes[0]


@dataclass(frozen=True, slots=True)
class FilmParseResult:
    """Structured parse of a film backup's filename."""

    title_hint: str
    year_hint: int | None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One result of a Provider search, in the Provider's order.

    The first result of a search becomes a Title's Match; the others are its
    Candidates. ``id`` is the Provider's own id (a TV show id is what an episode
    lookup takes). ``year`` is the release year for a film (always known) or the
    first-aired year for a show (``None`` when the Provider gives none).
    ``poster_ref`` is the Provider's Poster reference, such as TMDB's poster path
    or TheTVDB's image URL, or ``None``.
    """

    id: str
    name: str
    year: int | None
    poster_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeMetadata:
    """Resolved metadata for a TV episode."""

    show_title: str
    episode_title: str


@dataclass(frozen=True, slots=True)
class MovieMetadata:
    """Resolved metadata for a film."""

    title: str
    year: int


@dataclass(frozen=True, slots=True)
class PlanFingerprint:
    """Snapshot of on-disk state for staleness checks."""

    path: Path
    size: int
    mtime_ns: int


class EntryStatus(StrEnum):
    """The status of one entry of a Plan: a video or a Sidecar.

    A Sidecar whose video will not be applied has its video's status.
    """

    READY = "ready"
    NAME_TAKEN = "name taken"
    NO_MATCH = "no match"
    NOT_RECOGNISED = "not recognised"


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """The settings one Plan is built with, fixed for the life of that Plan.

    The session's settings owner makes them with the settings' rules applied:
    ``destination_root`` is the Destination root for ``mode``, and is ``None`` while
    ``folder_rename`` is off; ``season_folders`` holds only in TV Mode with
    ``folder_rename`` on.
    """

    mode: ScanMode
    provider_id: str
    destination_root: Path | None
    folder_rename: bool
    season_folders: bool


@dataclass(frozen=True, slots=True)
class Title:
    """One show or film of a Plan: its Match, or none, and the Candidates beside it.

    ``name`` is the Match's name, or the title hint read from the files when the
    search found nothing. ``year`` is the Match's year (a film's, or a show's first
    aired year when known), or for a Film Title with no Match the year hint.
    ``seasons`` lists the seasons of a TV Title's files.
    """

    name: str
    year: int | None
    seasons: tuple[int, ...]
    match: Candidate | None
    candidates: tuple[Candidate, ...]

    @property
    def poster_ref(self) -> str | None:
        """The Match's Poster reference, or ``None``."""
        return self.match.poster_ref if self.match is not None else None


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One video or Sidecar of a Plan.

    ``destination`` is ``None`` for an entry that is not applied for want of a name
    (no match, not recognised). ``video`` is a Sidecar's video, ``None`` for a video.
    ``root`` is the owning Source's folder, which the templates build under when the
    Destination root is unset. ``fingerprint`` holds the source's size and
    modification time at planning time.
    """

    source: Path
    destination: Path | None
    status: EntryStatus
    title: Title | None
    video: Path | None
    season: int | None
    episode: int | None
    root: Path
    fingerprint: PlanFingerprint

    @property
    def is_sidecar(self) -> bool:
        return self.video is not None

    @property
    def has_its_name(self) -> bool:
        """Whether the destination is the source, letter case included: Apply leaves
        the file where it is and reports it as unchanged."""
        return self.destination is not None and str(self.destination) == str(self.source)


@dataclass(frozen=True, slots=True)
class Plan:
    """The immutable batch that the Preview shows and Apply executes unchanged.

    Entries are in source-path order; Titles are in name order.
    """

    options: PlanOptions
    titles: tuple[Title, ...]
    entries: tuple[PlanEntry, ...]

    @property
    def mode(self) -> ScanMode:
        return self.options.mode

    @property
    def videos(self) -> tuple[PlanEntry, ...]:
        """The Plan's video entries, without the Sidecars, in source-path order."""
        return videos_of(self.entries)


class ApplyStatus(StrEnum):
    """Per-operation outcome."""

    RENAMED = "renamed"
    UNCHANGED = "unchanged"
    SKIP = "skip"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Result of a single apply operation."""

    source: Path
    destination: Path | None
    status: ApplyStatus
    reason: str


def videos_of(entries: Iterable[PlanEntry]) -> tuple[PlanEntry, ...]:
    """The video entries of ``entries``, without the Sidecars, in their order."""
    return tuple(entry for entry in entries if not entry.is_sidecar)
