"""Resolve parsed filenames to metadata via a provider."""

from __future__ import annotations

import logging

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, FilmParseResult, MovieMetadata, ParseResult
from termrenamer.util.errors import ProviderError

_LOG = logging.getLogger(__name__)


def fetch_episode_metadata(provider: TvMetadataProvider, parsed: ParseResult) -> EpisodeMetadata:
    """Look up episode metadata for a TV parse result."""
    return provider.resolve_tv_episode(
        show_hint=parsed.show_hint,
        season=parsed.season,
        episode=parsed.primary_episode,
    )


def fetch_film_metadata(provider: FilmMetadataProvider, parsed: FilmParseResult) -> MovieMetadata:
    """Look up film metadata for a film parse result.

    If the provider returns no match with a year filter, retries once without ``year_hint``
    (release year in the filename may not match TMDB indexing).
    """
    try:
        return provider.resolve_film(
            title_hint=parsed.title_hint,
            year_hint=parsed.year_hint,
        )
    except ProviderError as exc:
        if parsed.year_hint is None:
            raise
        _LOG.info(
            "No film metadata for %r year=%s: %s; retrying without year",
            parsed.title_hint,
            parsed.year_hint,
            exc,
        )
        try:
            return provider.resolve_film(
                title_hint=parsed.title_hint,
                year_hint=None,
            )
        except ProviderError as exc2:
            _LOG.info(
                "No film metadata for %r without year: %s",
                parsed.title_hint,
                exc2,
            )
            raise
