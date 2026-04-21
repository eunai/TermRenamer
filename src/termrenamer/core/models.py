"""Core data models for scan, parse, and rename planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ScanMode(StrEnum):
    """User-selected library mode."""

    TV = "tv"
    FILM = "film"


class FileKind(StrEnum):
    """Classification of a scanned path."""

    VIDEO = "video"
    SIDECAR = "sidecar"
    OTHER = "other"


class PlanEntryStatus(StrEnum):
    """Whether planning resolved metadata for this entry."""

    MATCHED = "matched"
    UNMATCHED = "unmatched"


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
    """Structured parse of a TV release filename."""

    show_hint: str
    season: int
    episodes: tuple[int, ...]

    @property
    def primary_episode(self) -> int:
        return self.episodes[0]


@dataclass(frozen=True, slots=True)
class FilmParseResult:
    """Structured parse of a film release filename."""

    title_hint: str
    year_hint: int | None


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


@dataclass(frozen=True, slots=True)
class RenamePlanEntry:
    """One planned rename operation."""

    source: Path
    destination: Path
    root: Path
    is_primary: bool
    primary_source: Path | None
    fingerprint: PlanFingerprint
    group_id: str
    status: PlanEntryStatus = PlanEntryStatus.MATCHED


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """Immutable batch of planned renames (preview/apply use the same object)."""

    entries: tuple[RenamePlanEntry, ...]
    mode: ScanMode


class ApplyStatus(StrEnum):
    """Per-operation outcome."""

    SUCCESS = "success"
    SKIP = "skip"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Result of a single apply operation."""

    source: Path
    destination: Path
    status: ApplyStatus
    reason: str
