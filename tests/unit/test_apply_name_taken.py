"""Apply under each Name taken value: what it renames, what it skips and why, what it never does."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.api.tmdb import StaticTvMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    EpisodeMetadata,
    Plan,
    PlanOptions,
    ScanMode,
)
from termrenamer.core.planning import plan_queue
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.util.errors import ValidationError

PILOT = "Show Name - S01E01 - Pilot"


def _plan(sources: list[Path], policy: NameTakenPolicy) -> Plan:
    provider = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=False,
        season_folders=False,
        name_taken=policy,
    )
    return plan_queue(sources, options, provider).plan


def _by_name(results: list[ApplyResult]) -> dict[str, tuple[ApplyStatus, str]]:
    return {r.source.name: (r.status, r.reason) for r in results}


def _contents(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def _taken_folder(tmp_path: Path) -> Path:
    """A video and its subtitle whose new name is already used; returns the video."""
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"new")
    (tmp_path / "Show.Name.S01E01.srt").write_bytes(b"subs")
    (tmp_path / f"{PILOT}.mkv").write_bytes(b"old")
    return tmp_path / "Show.Name.S01E01.mkv"


def test_under_suffix_a_taken_name_is_applied_with_its_number(tmp_path: Path) -> None:
    video = _taken_folder(tmp_path)
    folder = video.parent

    results = apply_plan(_plan([video], NameTakenPolicy.SUFFIX), confirmed=True)

    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.RENAMED, "ok"),
        "Show.Name.S01E01.srt": (ApplyStatus.RENAMED, "ok"),
    }
    assert _contents(folder) == {
        f"{PILOT}.mkv": b"old",
        f"{PILOT} (1).mkv": b"new",
        f"{PILOT} (1).srt": b"subs",
    }


def test_under_skip_a_taken_name_and_its_sidecar_are_skipped_as_name_taken(
    tmp_path: Path,
) -> None:
    video = _taken_folder(tmp_path)
    folder = video.parent

    results = apply_plan(_plan([video], NameTakenPolicy.SKIP), confirmed=True)

    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.SKIP, "name taken"),
        "Show.Name.S01E01.srt": (ApplyStatus.SKIP, "name taken"),
    }
    assert _contents(folder) == {
        "Show.Name.S01E01.mkv": b"new",
        "Show.Name.S01E01.srt": b"subs",
        f"{PILOT}.mkv": b"old",
    }


def test_under_skip_a_sidecar_whose_own_name_is_taken_stays_while_its_video_moves(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"new")
    (tmp_path / "Show.Name.S01E01.srt").write_bytes(b"subs")
    (tmp_path / f"{PILOT}.srt").write_bytes(b"old subs")

    results = apply_plan(
        _plan([tmp_path / "Show.Name.S01E01.mkv"], NameTakenPolicy.SKIP), confirmed=True
    )

    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.RENAMED, "ok"),
        "Show.Name.S01E01.srt": (ApplyStatus.SKIP, "name taken"),
    }
    assert _contents(tmp_path) == {
        f"{PILOT}.mkv": b"new",
        "Show.Name.S01E01.srt": b"subs",
        f"{PILOT}.srt": b"old subs",
    }


@pytest.mark.parametrize("policy", list(NameTakenPolicy))
def test_nothing_is_renamed_before_the_confirmation(
    tmp_path: Path, policy: NameTakenPolicy
) -> None:
    video = _taken_folder(tmp_path)
    folder = video.parent
    plan = _plan([video], policy)
    before = _contents(folder)

    with pytest.raises(ValidationError):
        apply_plan(plan, confirmed=False)

    assert _contents(folder) == before


@pytest.mark.parametrize("policy", list(NameTakenPolicy))
def test_a_name_taken_after_the_preview_is_never_overwritten(
    tmp_path: Path, policy: NameTakenPolicy
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"new")
    plan = _plan([tmp_path / "Show.Name.S01E01.mkv"], policy)
    (tmp_path / f"{PILOT}.mkv").write_bytes(b"arrived later")

    results = apply_plan(plan, confirmed=True)

    assert _by_name(results) == {
        "Show.Name.S01E01.mkv": (ApplyStatus.SKIP, "destination exists at apply time"),
    }
    assert _contents(tmp_path) == {
        "Show.Name.S01E01.mkv": b"new",
        f"{PILOT}.mkv": b"arrived later",
    }


def test_the_plan_is_applied_as_previewed_whatever_the_name_on_disk_does_later(
    tmp_path: Path,
) -> None:
    """A Plan built under ``skip`` keeps its skip after the taken name is freed."""
    video = _taken_folder(tmp_path)
    folder = video.parent
    plan = _plan([video], NameTakenPolicy.SKIP)
    (folder / f"{PILOT}.mkv").unlink()

    results = apply_plan(plan, confirmed=True)

    assert _by_name(results)["Show.Name.S01E01.mkv"] == (ApplyStatus.SKIP, "name taken")
    assert sorted(_contents(folder)) == ["Show.Name.S01E01.mkv", "Show.Name.S01E01.srt"]
