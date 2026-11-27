"""Confirm-before-apply integration checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import plan_folder
from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import EpisodeMetadata, ScanMode
from termrenamer.util.errors import ValidationError


def test_no_filesystem_change_without_confirm(tmp_path: Path) -> None:
    src = tmp_path / "Show.S01E01.mkv"
    src.write_bytes(b"1")
    provider = StaticTvMetadataProvider(
        _mapping={("show", 1, 1): EpisodeMetadata(show_title="Show", episode_title="Pilot")},
    )
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
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
    plan = plan_folder(tmp_path, ScanMode.TV, provider)
    apply_plan(plan, confirmed=True)
    assert not src.exists()
