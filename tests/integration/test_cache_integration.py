"""Integration: cache file on disk under tmp_path."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.caching import CachedTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata
from termrenamer.persistence.cache import SqliteMetadataCache


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "meta.db"
    meta = EpisodeMetadata(show_title="Show", episode_title="One")
    c1 = SqliteMetadataCache(db)
    c1.put_tv_episode(show_hint="sh", season=2, episode=3, metadata=meta)
    c1.close()

    c2 = SqliteMetadataCache(db)
    assert c2.get_tv_episode(show_hint="sh", season=2, episode=3) == meta
    c2.close()


def test_cached_provider_second_call_hits_disk_cache(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    cache = SqliteMetadataCache(db)
    calls = 0

    class Counting:
        def resolve_tv_episode(
            self,
            *,
            show_hint: str,
            season: int,
            episode: int,
        ) -> EpisodeMetadata:
            nonlocal calls
            calls += 1
            return EpisodeMetadata(show_title="S", episode_title="E")

    wrapped = CachedTvMetadataProvider(Counting(), cache)
    wrapped.resolve_tv_episode(show_hint="a", season=1, episode=1)
    wrapped.resolve_tv_episode(show_hint="a", season=1, episode=1)
    assert calls == 1
