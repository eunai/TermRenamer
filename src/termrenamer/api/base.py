"""Provider protocols for metadata resolution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from termrenamer.core.models import EpisodeMetadata, MovieMetadata


@runtime_checkable
class TvMetadataProvider(Protocol):
    """Supplies TV episode/show metadata for planning."""

    def resolve_tv_episode(
        self,
        *,
        show_hint: str,
        season: int,
        episode: int,
    ) -> EpisodeMetadata:
        """Return resolved titles for a TV episode."""
        ...


@runtime_checkable
class FilmMetadataProvider(Protocol):
    """Supplies film metadata for planning."""

    def resolve_film(
        self,
        *,
        title_hint: str,
        year_hint: int | None,
    ) -> MovieMetadata:
        """Return resolved title and release year for a film."""
        ...


# Backwards-compatible alias for TV-only call sites.
MetadataProvider = TvMetadataProvider
