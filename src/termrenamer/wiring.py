"""Construct metadata providers for planning.

HTTP + optional cache live here — not in ``tui/`` (no raw HTTP in the TUI layer).
"""

from __future__ import annotations

from dataclasses import dataclass

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.api.omdb import OmdbProvider
from termrenamer.api.tmdb import TmdbProvider
from termrenamer.api.tvdb_v4 import TvdbV4Provider
from termrenamer.app_bootstrap import (
    Settings,
    bootstrap,
    create_http_client,
    create_metadata_cache,
    where_to_set,
)
from termrenamer.core.models import PROVIDER_IDS, ScanMode
from termrenamer.persistence.cache import SqliteMetadataCache
from termrenamer.persistence.posters import PosterStore, cache_folder, poster_folder
from termrenamer.util.errors import ValidationError
from termrenamer.util.http import HttpClient


def _tmdb_missing_message() -> str:
    return f"TMDB requires an API key: {where_to_set('TERMRENAMER_TMDB_API_KEY')}."


@dataclass(frozen=True, slots=True)
class PlanningWiring:
    """TV + film providers for :func:`termrenamer.core.planning.plan_queue`.

    Each Provider is present, or ``None`` when its key is missing. No Provider is
    required on its own; selecting one with no key is reported when a plan is built.
    ``cache`` is the lookup cache, or ``None`` when ``TERMRENAMER_CACHE_DB_PATH`` is
    unset. :meth:`resolve_tv` and :meth:`resolve_film` return a new lookup for one
    build each time they are called. ``posters`` is the poster store, which downloads
    through the same HTTP client, or ``None`` (no Poster is then shown).
    """

    tv_tmdb: TvMetadataProvider | None
    tv_tvdb: TvMetadataProvider | None
    film: FilmMetadataProvider | None
    film_omdb: FilmMetadataProvider | None
    cache: SqliteMetadataCache | None = None
    posters: PosterStore | None = None

    def keyed_providers(self) -> dict[ScanMode, frozenset[str]]:
        """Return, per Mode, the ids of the Providers whose key is set."""
        providers: dict[ScanMode, dict[str, object | None]] = {
            ScanMode.TV: {"tmdb": self.tv_tmdb, "tvdb": self.tv_tvdb},
            ScanMode.FILM: {"tmdb": self.film, "omdb": self.film_omdb},
        }
        return {
            mode: frozenset(pid for pid in PROVIDER_IDS[mode] if providers[mode][pid] is not None)
            for mode in ScanMode
        }

    def resolve(self, *, mode: ScanMode, provider_id: str) -> TvLookup | FilmLookup:
        """Return one build's lookup for ``mode`` through ``provider_id``, over the cache."""
        if mode is ScanMode.TV:
            return self.resolve_tv(provider_id=provider_id)
        return self.resolve_film(provider_id=provider_id)

    def resolve_tv(self, *, provider_id: str) -> TvLookup:
        """Return one build's TV lookup through ``tmdb`` or ``tvdb``, over the cache."""
        if provider_id == "tmdb":
            if self.tv_tmdb is None:
                raise ValidationError(_tmdb_missing_message())
            return TvLookup(self.tv_tmdb, cache=self.cache, provider_id=provider_id)
        if provider_id == "tvdb":
            if self.tv_tvdb is None:
                msg = (
                    "TheTVDB requires an API key: "
                    f"{where_to_set('TERMRENAMER_TVDB_API_KEY')}. "
                    "Set TERMRENAMER_TVDB_SUBSCRIBER_PIN the same way if your account needs it."
                )
                raise ValidationError(msg)
            return TvLookup(self.tv_tvdb, cache=self.cache, provider_id=provider_id)
        msg = f"Unknown TV provider id: {provider_id!r}"
        raise ValidationError(msg)

    def resolve_film(self, *, provider_id: str) -> FilmLookup:
        """Return one build's film lookup through ``tmdb`` or ``omdb``, over the cache."""
        if provider_id == "tmdb":
            if self.film is None:
                raise ValidationError(_tmdb_missing_message())
            return FilmLookup(self.film, cache=self.cache, provider_id=provider_id)
        if provider_id == "omdb":
            if self.film_omdb is None:
                msg = f"OMDb requires an API key: {where_to_set('TERMRENAMER_OMDB_API_KEY')}."
                raise ValidationError(msg)
            return FilmLookup(self.film_omdb, cache=self.cache, provider_id=provider_id)
        msg = f"Unknown film provider id: {provider_id!r}"
        raise ValidationError(msg)


def build_planning_wiring(settings: Settings, http: HttpClient) -> PlanningWiring:
    """Build each Provider whose key is set, and the lookup cache when one is configured."""
    tv_tmdb: TvMetadataProvider | None = None
    film: FilmMetadataProvider | None = None
    if settings.has_tmdb_credentials and settings.tmdb_api_key:
        tmdb = TmdbProvider(http, api_key=settings.tmdb_api_key)
        tv_tmdb = tmdb
        film = tmdb
    tv_tvdb: TvMetadataProvider | None = None
    if settings.has_tvdb_credentials and settings.tvdb_api_key:
        tv_tvdb = TvdbV4Provider(
            http,
            api_key=settings.tvdb_api_key,
            subscriber_pin=settings.tvdb_subscriber_pin,
        )
    film_omdb: FilmMetadataProvider | None = None
    if settings.has_omdb_credentials and settings.omdb_api_key:
        film_omdb = OmdbProvider(http, api_key=settings.omdb_api_key)

    return PlanningWiring(
        tv_tmdb=tv_tmdb,
        tv_tvdb=tv_tvdb,
        film=film,
        film_omdb=film_omdb,
        cache=create_metadata_cache(settings),
        posters=PosterStore(poster_folder(), http, inside=cache_folder()),
    )


def bootstrap_wiring() -> tuple[Settings, PlanningWiring]:
    """Load settings, HTTP client, and planning wiring (used by ``python -m termrenamer``)."""
    settings = bootstrap()
    http = create_http_client(settings)
    wiring = build_planning_wiring(settings, http)
    return settings, wiring
