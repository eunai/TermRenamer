"""The Provider seam: searches that return ordered Candidates, and episode titles.

Every method separates "nothing found" from "the lookup failed":

- nothing found is an empty tuple from a search, or ``None`` from an episode lookup;
- a failure (network, authentication, rate limit, an unusable response after the
  HTTP client's retries) raises :class:`~termrenamer.util.errors.ProviderError`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from termrenamer.core.models import Candidate


@runtime_checkable
class TvMetadataProvider(Protocol):
    """A TV Provider: search shows by hint, and an episode's title by show id."""

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        """Return the shows found for ``hint``, in the Provider's order."""
        ...

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        """Return the episode's title, or ``None`` when the Provider has no such episode."""
        ...


@runtime_checkable
class FilmMetadataProvider(Protocol):
    """A Film Provider: search films by title hint and optional year."""

    def search_films(self, *, hint: str, year: int | None) -> tuple[Candidate, ...]:
        """Return the films found, in the Provider's order; each has a year."""
        ...


@runtime_checkable
class BuildScopedTvProvider(Protocol):
    """A TV Provider that keeps state for one build, such as a show's episode list.

    :class:`~termrenamer.api.lookup.TvLookup` calls :meth:`for_build` once per build
    and sends that build's lookups to the object it returns.
    """

    def for_build(self) -> TvMetadataProvider:
        """Return a Provider view whose state lasts for one build."""
        ...


def leading_year(value: object) -> int | None:
    """Return the year a Provider date starts with (``"2011-05-20"``, ``"2011–2014"``)."""
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def text_field(record: dict[str, object], *names: str) -> str | None:
    """Return the first of ``names`` that holds non-blank text, stripped."""
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def id_field(record: dict[str, object], name: str) -> str | None:
    """Return a record's id (a number or non-blank text) as text, or ``None``."""
    value = record.get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
