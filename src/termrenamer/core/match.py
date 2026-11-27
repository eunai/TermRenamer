"""Resolve parsed filenames to metadata through the Provider seam.

Each helper takes the first result of a search as the Match, as planning always has.
``None`` means nothing found; a failure raises
:class:`~termrenamer.util.errors.ProviderError`.
"""

from __future__ import annotations

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, FilmParseResult, MovieMetadata, ParseResult
from termrenamer.util.errors import ProviderError


def fetch_episode_metadata(
    provider: TvMetadataProvider,
    parsed: ParseResult,
) -> EpisodeMetadata | None:
    """Search the show hint, then look the episode up in the first show found."""
    shows = provider.search_shows(hint=parsed.show_hint)
    if not shows:
        return None
    match = shows[0]
    title = provider.episode_title(
        show_id=match.id,
        season=parsed.season,
        episode=parsed.primary_episode,
    )
    if title is None:
        return None
    return EpisodeMetadata(show_title=match.name, episode_title=title)


def fetch_film_metadata(
    provider: FilmMetadataProvider,
    parsed: FilmParseResult,
) -> MovieMetadata | None:
    """Search the title hint and year hint, and take the first film found.

    Pass a :class:`~termrenamer.api.lookup.FilmLookup` to get the retry without the
    year when the search with it finds nothing.
    """
    films = provider.search_films(hint=parsed.title_hint, year=parsed.year_hint)
    if not films:
        return None
    match = films[0]
    if match.year is None:
        raise ProviderError("Film search result missing a release year")
    return MovieMetadata(title=match.name, year=match.year)
