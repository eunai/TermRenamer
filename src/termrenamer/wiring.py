"""Construct metadata providers for planning.

HTTP + optional cache live here — not in ``tui/`` (no raw HTTP in the TUI layer).
"""

from __future__ import annotations

from dataclasses import dataclass

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.api.caching import CachedFilmMetadataProvider, CachedTvMetadataProvider
from termrenamer.api.omdb import OmdbProvider
from termrenamer.api.tmdb import TmdbProvider
from termrenamer.api.tvdb_v4 import TvdbV4Provider
from termrenamer.app_bootstrap import Settings, bootstrap, create_http_client, create_metadata_cache
from termrenamer.util.errors import ValidationError
from termrenamer.util.http import HttpClient


@dataclass(frozen=True, slots=True)
class PlanningWiring:
    """Resolved TV + film providers for :func:`termrenamer.core.planning.build_rename_plan`."""

    tv_tmdb: TvMetadataProvider
    tv_tvdb: TvMetadataProvider | None
    film: FilmMetadataProvider
    film_omdb: FilmMetadataProvider | None

    def resolve_tv(self, *, provider_id: str) -> TvMetadataProvider:
        """Return the TV metadata provider for ``tmdb`` or ``tvdb``."""
        if provider_id == "tmdb":
            return self.tv_tmdb
        if provider_id == "tvdb":
            if self.tv_tvdb is None:
                msg = (
                    "TheTVDB requires TERMRENAMER_TVDB_API_KEY (and PIN if your account needs it) "
                    "in the environment or .env — see .env.example."
                )
                raise ValidationError(msg)
            return self.tv_tvdb
        msg = f"Unknown TV provider id: {provider_id!r}"
        raise ValidationError(msg)

    def resolve_film(self, *, provider_id: str) -> FilmMetadataProvider:
        """Return the film metadata provider for ``tmdb`` or ``omdb``."""
        if provider_id == "tmdb":
            return self.film
        if provider_id == "omdb":
            if self.film_omdb is None:
                msg = (
                    "OMDb requires TERMRENAMER_OMDB_API_KEY in the environment or .env "
                    "— see .env.example."
                )
                raise ValidationError(msg)
            return self.film_omdb
        msg = f"Unknown film provider id: {provider_id!r}"
        raise ValidationError(msg)


def build_planning_wiring(settings: Settings, http: HttpClient) -> PlanningWiring:
    """Build TMDB (+ optional TVDB/OMDb) providers with optional SQLite cache wrappers."""
    if not settings.tmdb_api_key:
        msg = "TMDB API key is required for planning wiring"
        raise ValidationError(msg)
    tmdb = TmdbProvider(http, api_key=settings.tmdb_api_key)
    cache = create_metadata_cache(settings)
    tv_tmdb: TvMetadataProvider = (
        CachedTvMetadataProvider(tmdb, cache) if cache is not None else tmdb
    )
    film: FilmMetadataProvider = (
        CachedFilmMetadataProvider(tmdb, cache) if cache is not None else tmdb
    )
    tv_tvdb: TvMetadataProvider | None = None
    if settings.has_tvdb_credentials and settings.tvdb_api_key:
        raw = TvdbV4Provider(
            http,
            api_key=settings.tvdb_api_key,
            subscriber_pin=settings.tvdb_subscriber_pin,
        )
        tv_tvdb = CachedTvMetadataProvider(raw, cache) if cache is not None else raw

    film_omdb: FilmMetadataProvider | None = None
    if settings.has_omdb_credentials and settings.omdb_api_key:
        film_omdb = OmdbProvider(http, api_key=settings.omdb_api_key)

    return PlanningWiring(tv_tmdb=tv_tmdb, tv_tvdb=tv_tvdb, film=film, film_omdb=film_omdb)


def bootstrap_wiring(*, require_tmdb_key: bool = True) -> tuple[Settings, PlanningWiring]:
    """Load settings, HTTP client, and planning wiring (used by ``python -m termrenamer``)."""
    settings = bootstrap(require_tmdb_key=require_tmdb_key)
    http = create_http_client(settings)
    wiring = build_planning_wiring(settings, http)
    return settings, wiring
