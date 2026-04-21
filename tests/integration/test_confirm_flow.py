"""Confirm-before-apply integration checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import EpisodeMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan
from termrenamer.util.errors import ValidationError


def test_no_filesystem_change_without_confirm(tmp_path: Path) -> None:
    src = tmp_path / "Show.S01E01.mkv"
    src.write_bytes(b"1")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    assert plan.entries
    with pytest.raises(ValidationError):
        apply_plan(plan, confirmed=False)
    assert src.exists()
    assert src.read_bytes() == b"1"


def test_confirm_applies(tmp_path: Path) -> None:
    src = tmp_path / "Show.S01E01.mkv"
    src.write_bytes(b"1")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.TV, provider=provider)
    apply_plan(plan, confirmed=True)
    assert not src.exists()
