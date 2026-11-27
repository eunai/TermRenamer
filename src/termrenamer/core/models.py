"""Core data models for scan, parse, and rename planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from termrenamer.core.policies import NameTakenPolicy


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

    A Sidecar whose video will not be applied has its video's status. A left out
    entry is one the person took out of the Plan; Apply does not touch it.
    """

    READY = "ready"
    NAME_TAKEN = "name taken"
    NO_MATCH = "no match"
    NOT_RECOGNISED = "not recognised"
    LEFT_OUT = "left out"


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """The settings one Plan is built with, fixed for the life of that Plan.

    The session's settings owner makes them with the settings' rules applied:
    ``destination_root`` is the Destination root for ``mode``, and is ``None`` while
    ``folder_rename`` is off; ``season_folders`` holds only in TV Mode with
    ``folder_rename`` on. ``name_taken`` is the Name taken setting: a file whose new
    name is taken gets a number (``SUFFIX``) or is not applied (``SKIP``).
    """

    mode: ScanMode
    provider_id: str
    destination_root: Path | None
    folder_rename: bool
    season_folders: bool
    name_taken: NameTakenPolicy = NameTakenPolicy.SUFFIX


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

    ``destination`` is ``None`` for an entry that is not applied (no match, not
    recognised, left out, name taken under ``skip``). ``video`` is a Sidecar's video,
    ``None`` for a video. ``root`` is the owning Source's folder, which the templates
    build under when the Destination root is unset. ``fingerprint`` holds the source's
    size and modification time at planning time. ``wanted`` is the name the templates
    give a video for its Match, before Name taken numbers or skips it, and ``None``
    for a Sidecar and for a video with no name (no match, not recognised): deriving a
    Plan claims names again from it.
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
    wanted: Path | None = None

    @property
    def is_sidecar(self) -> bool:
        return self.video is not None

    @property
    def has_its_name(self) -> bool:
        """Whether the destination is the source, letter case included: Apply leaves
        the file where it is and reports it as unchanged."""
        return self.destination is not None and str(self.destination) == str(self.source)

    @property
    def skipped_for_name_taken(self) -> bool:
        """Whether its name is taken and it is not applied (Name taken set to ``skip``)."""
        return self.status is EntryStatus.NAME_TAKEN and self.destination is None

    @property
    def to_apply(self) -> bool:
        """Whether Apply applies it: ready, or name taken with a numbered name. Only such
        an entry claims its name."""
        return self.destination is not None and self.status in (
            EntryStatus.READY,
            EntryStatus.NAME_TAKEN,
        )


@dataclass(frozen=True, slots=True)
class SourceFolder:
    """A source folder that is a folder Source or lies inside one, and its direct
    children as found when the Plan was built: ``files`` (a symbolic link counts as a
    file) and ``folders``. A source folder is the parent folder of an entry."""

    path: Path
    files: tuple[Path, ...]
    folders: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class Straggler:
    """A file or folder left in a source folder that Apply merges into a target folder
    (a folder an entry of the Plan moves into), at the path the Plan fixed for it.

    ``source`` is the child as found when the Plan was built; its parent is the source
    folder. ``destination`` is its path in the target folder.
    """

    source: Path
    destination: Path


@dataclass(frozen=True, slots=True)
class Plan:
    """The immutable batch that the Preview shows and Apply executes unchanged.

    Entries and Stragglers are in source-path order; Titles are in name order.
    ``source_folders`` holds the children of each source folder that Stragglers are
    listed from; a Plan built with Folder rename off lists no Stragglers.
    """

    options: PlanOptions
    titles: tuple[Title, ...]
    entries: tuple[PlanEntry, ...]
    stragglers: tuple[Straggler, ...] = ()
    source_folders: tuple[SourceFolder, ...] = ()

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
    LEFT_OUT = "left out"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What Apply did with one entry or one Straggler, and why."""

    source: Path
    destination: Path | None
    status: ApplyStatus
    reason: str


@dataclass(frozen=True, slots=True)
class Move:
    """One file or folder Apply moved, from ``source`` to ``destination``.

    ``fingerprint`` is a file's size and modification time at its new place, taken
    without following symbolic links; ``None`` for a folder.
    """

    source: Path
    destination: Path
    fingerprint: PlanFingerprint | None


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """Everything one Apply did, in the order it did it; Undo reverses it from this alone.

    ``results`` holds one result per entry: videos in source-path order, then Sidecars.
    ``stragglers`` holds one result per Straggler of the Plan, in the Plan's order; a
    Straggler that moved is ``RENAMED``. ``moves`` lists every move: the entries renamed,
    in ``results`` order, then the Stragglers moved. ``folders_created`` lists each folder
    Apply made, each before the folders inside it. ``folders_removed`` lists each emptied
    source folder Apply removed after every move, each before its parent.
    """

    results: tuple[ApplyResult, ...]
    stragglers: tuple[ApplyResult, ...]
    moves: tuple[Move, ...]
    folders_created: tuple[Path, ...]
    folders_removed: tuple[Path, ...]

    @property
    def stragglers_merged(self) -> int:
        """How many Stragglers Apply moved."""
        return sum(1 for r in self.stragglers if r.status is ApplyStatus.RENAMED)


def videos_of(entries: Iterable[PlanEntry]) -> tuple[PlanEntry, ...]:
    """The video entries of ``entries``, without the Sidecars, in their order."""
    return tuple(entry for entry in entries if not entry.is_sidecar)
