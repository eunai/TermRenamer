"""Leave a file out, and put it back: each change derives a new Plan from the old one.

Real temporary folders and a stand-in Provider, through :func:`plan_queue` and
:func:`derive_plan`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from termrenamer.core.models import Candidate, EntryStatus, Plan, PlanEntry, PlanOptions, ScanMode
from termrenamer.core.planning import LeaveOut, PutBack, derive_plan, plan_queue
from termrenamer.core.policies import NameTakenPolicy

from .links import point_folder_at

PILOT = "Show Name - S01E01 - Pilot"


@dataclass
class TvStandIn:
    """Answers show searches and episode titles from fixed data, and counts the lookups."""

    shows: dict[str, tuple[Candidate, ...]]
    episodes: dict[tuple[str, int, int], str]
    lookups: list[str] = field(default_factory=list)

    def search_shows(self, *, hint: str) -> tuple[Candidate, ...]:
        self.lookups.append(hint)
        return self.shows.get(hint.casefold().strip(), ())

    def episode_title(self, *, show_id: str, season: int, episode: int) -> str | None:
        self.lookups.append(f"{show_id} {season} {episode}")
        return self.episodes.get((show_id, season, episode))


def _show_name() -> TvStandIn:
    return TvStandIn(
        shows={"show name": (Candidate(id="1", name="Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )


def _options(policy: NameTakenPolicy, *, library: Path | None = None) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=library,
        folder_rename=library is not None,
        season_folders=False,
        name_taken=policy,
    )


def _two_discs(tmp_path: Path) -> list[Path]:
    """Disc A and Disc B each hold the Pilot with its subtitle."""
    for disc in ("Disc A", "Disc B"):
        (tmp_path / disc).mkdir()
        (tmp_path / disc / "Show.Name.S01E01.mkv").write_bytes(disc.encode())
        (tmp_path / disc / "Show.Name.S01E01.srt").write_text(disc, encoding="utf-8")
    return [tmp_path / "Disc B", tmp_path / "Disc A"]


def _summary(plan: Plan) -> list[tuple[str, str, str | None, EntryStatus]]:
    return [
        (
            e.source.parent.name,
            e.source.name,
            e.destination.name if e.destination is not None else None,
            e.status,
        )
        for e in plan.entries
    ]


def _video(plan: Plan, disc: str) -> PlanEntry:
    return next(v for v in plan.videos if v.source.parent.name == disc)


def test_a_video_left_out_has_no_destination_and_its_sidecars_follow(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"1")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    (tmp_path / "Show.Name.S01E01.nfo").write_text("n", encoding="utf-8")
    (tmp_path / "Show.Name.S01E02.mkv").write_bytes(b"2")
    plan = plan_queue([tmp_path], _options(NameTakenPolicy.SUFFIX), _show_name()).plan
    pilot = next(v for v in plan.videos if v.episode == 1)

    derived = derive_plan(plan, LeaveOut(pilot))

    second = "Show Name - S01E02 - Second.mkv"
    assert _summary(derived) == [
        (tmp_path.name, "Show.Name.S01E01.mkv", None, EntryStatus.LEFT_OUT),
        (tmp_path.name, "Show.Name.S01E01.nfo", None, EntryStatus.LEFT_OUT),
        (tmp_path.name, "Show.Name.S01E01.srt", None, EntryStatus.LEFT_OUT),
        (tmp_path.name, "Show.Name.S01E02.mkv", second, EntryStatus.READY),
    ]
    # The Plan never changes: the change made a new one.
    assert pilot in plan.entries
    assert derived.titles == plan.titles
    assert derived.options == plan.options


def test_deriving_a_plan_makes_no_provider_lookup(tmp_path: Path) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"1")
    provider = _show_name()
    plan = plan_queue([tmp_path], _options(NameTakenPolicy.SUFFIX), provider).plan
    lookups = list(provider.lookups)
    [video] = plan.videos

    left_out = derive_plan(plan, LeaveOut(video))
    derive_plan(left_out, PutBack(left_out.videos[0]))

    assert provider.lookups == lookups


def test_under_suffix_a_name_only_the_left_out_file_had_claimed_is_free_for_the_next(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SUFFIX, library=library), _show_name()
    ).plan
    assert _summary(plan)[2:] == [
        ("Disc B", "Show.Name.S01E01.mkv", f"{PILOT} (1).mkv", EntryStatus.NAME_TAKEN),
        ("Disc B", "Show.Name.S01E01.srt", f"{PILOT} (1).srt", EntryStatus.READY),
    ]

    derived = derive_plan(plan, LeaveOut(_video(plan, "Disc A")))

    assert _summary(derived) == [
        ("Disc A", "Show.Name.S01E01.mkv", None, EntryStatus.LEFT_OUT),
        ("Disc A", "Show.Name.S01E01.srt", None, EntryStatus.LEFT_OUT),
        ("Disc B", "Show.Name.S01E01.mkv", f"{PILOT}.mkv", EntryStatus.READY),
        ("Disc B", "Show.Name.S01E01.srt", f"{PILOT}.srt", EntryStatus.READY),
    ]


def test_under_skip_a_name_only_the_left_out_file_had_claimed_is_free_for_the_next(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SKIP, library=library), _show_name()
    ).plan
    assert _summary(plan)[2:] == [
        ("Disc B", "Show.Name.S01E01.mkv", None, EntryStatus.NAME_TAKEN),
        ("Disc B", "Show.Name.S01E01.srt", None, EntryStatus.NAME_TAKEN),
    ]

    derived = derive_plan(plan, LeaveOut(_video(plan, "Disc A")))

    assert _summary(derived)[2:] == [
        ("Disc B", "Show.Name.S01E01.mkv", f"{PILOT}.mkv", EntryStatus.READY),
        ("Disc B", "Show.Name.S01E01.srt", f"{PILOT}.srt", EntryStatus.READY),
    ]


@pytest.mark.parametrize("policy", [NameTakenPolicy.SUFFIX, NameTakenPolicy.SKIP])
@pytest.mark.parametrize("disc", ["Disc A", "Disc B"])
def test_a_video_put_back_has_the_statuses_a_fresh_plan_gives(
    tmp_path: Path, policy: NameTakenPolicy, disc: str
) -> None:
    library = tmp_path / "Library"
    queue = _two_discs(tmp_path)
    plan = plan_queue(queue, _options(policy, library=library), _show_name()).plan
    left_out = derive_plan(plan, LeaveOut(_video(plan, disc)))
    put_back = derive_plan(left_out, PutBack(_video(left_out, disc)))

    fresh = plan_queue(queue, _options(policy, library=library), _show_name()).plan
    assert put_back.entries == fresh.entries
    assert put_back == fresh


def test_deriving_tests_each_wanted_path_on_disk_again(tmp_path: Path) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SUFFIX, library=library), _show_name()
    ).plan
    # Something arrives at the wanted name after the Plan was built.
    (library / "Show Name").mkdir(parents=True)
    (library / "Show Name" / f"{PILOT}.mkv").write_bytes(b"arrived")

    derived = derive_plan(plan, LeaveOut(_video(plan, "Disc B")))

    assert _summary(derived)[:2] == [
        ("Disc A", "Show.Name.S01E01.mkv", f"{PILOT} (1).mkv", EntryStatus.NAME_TAKEN),
        ("Disc A", "Show.Name.S01E01.srt", f"{PILOT} (1).srt", EntryStatus.READY),
    ]


def test_a_video_skipped_for_a_taken_name_can_be_left_out_and_put_back(tmp_path: Path) -> None:
    library = tmp_path / "Library"
    queue = _two_discs(tmp_path)
    plan = plan_queue(queue, _options(NameTakenPolicy.SKIP, library=library), _show_name()).plan
    skipped = _video(plan, "Disc B")
    assert skipped.skipped_for_name_taken

    left_out = derive_plan(plan, LeaveOut(skipped))
    assert _video(left_out, "Disc B").status is EntryStatus.LEFT_OUT

    assert derive_plan(left_out, PutBack(_video(left_out, "Disc B"))) == plan


def test_no_match_and_not_recognised_files_cannot_be_left_out(tmp_path: Path) -> None:
    (tmp_path / "Unknown.Show.S01E01.mkv").write_bytes(b"1")
    (tmp_path / "Show.Name.S01E05.mkv").write_bytes(b"5")
    (tmp_path / "holiday video.mkv").write_bytes(b"h")
    plan = plan_queue([tmp_path], _options(NameTakenPolicy.SUFFIX), _show_name()).plan
    statuses = {v.status for v in plan.videos}
    assert statuses == {EntryStatus.NO_MATCH, EntryStatus.NOT_RECOGNISED}

    for video in plan.videos:
        with pytest.raises(ValueError, match="cannot be left out"):
            derive_plan(plan, LeaveOut(video))


def test_a_sidecar_cannot_be_left_out_on_its_own_and_only_a_left_out_video_is_put_back(
    tmp_path: Path,
) -> None:
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"1")
    (tmp_path / "Show.Name.S01E01.srt").write_text("s", encoding="utf-8")
    plan = plan_queue([tmp_path], _options(NameTakenPolicy.SUFFIX), _show_name()).plan
    video, sidecar = plan.entries[0], plan.entries[1]
    assert sidecar.is_sidecar

    with pytest.raises(ValueError, match="cannot be left out"):
        derive_plan(plan, LeaveOut(sidecar))
    with pytest.raises(ValueError, match="is not left out"):
        derive_plan(plan, PutBack(video))
    with pytest.raises(ValueError, match="not in the Plan"):
        derive_plan(plan, LeaveOut(replace(video, source=tmp_path / "elsewhere.mkv")))


def test_leave_out_changes_the_entry_named_even_when_its_folder_now_points_elsewhere(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SUFFIX, library=library), _show_name()
    ).plan
    # After planning, Disc B is swapped for a link to Disc A.
    (tmp_path / "Disc B").rename(tmp_path / "Disc B moved")
    point_folder_at(tmp_path / "Disc B", tmp_path / "Disc A")

    derived = derive_plan(plan, LeaveOut(_video(plan, "Disc B")))

    assert [(e.source.parent.name, e.status) for e in derived.videos] == [
        ("Disc A", EntryStatus.READY),
        ("Disc B", EntryStatus.LEFT_OUT),
    ]


def _redirect_disc_b_before_disc_a(tmp_path: Path) -> None:
    """After planning, Disc B becomes a link to a copy that sorts before Disc A."""
    copy = tmp_path / "Aaa"
    copy.mkdir()
    for name in ("Show.Name.S01E01.mkv", "Show.Name.S01E01.srt"):
        (copy / name).write_bytes((tmp_path / "Disc B" / name).read_bytes())
    (tmp_path / "Disc B").rename(tmp_path / "Disc B moved")
    point_folder_at(tmp_path / "Disc B", copy)


def test_a_derived_plan_keeps_the_order_the_build_recorded_when_a_folder_is_redirected(
    tmp_path: Path,
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SUFFIX, library=library), _show_name()
    ).plan
    _redirect_disc_b_before_disc_a(tmp_path)

    left_out = derive_plan(plan, LeaveOut(_video(plan, "Disc B")))
    put_back = derive_plan(left_out, PutBack(_video(left_out, "Disc B")))

    assert [e.source for e in left_out.entries] == [e.source for e in plan.entries]
    # Disc A still claims first, so Disc B gets the number again, as in the build.
    assert put_back == plan


def test_deriving_never_resolves_a_source_path_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Library"
    plan = plan_queue(
        _two_discs(tmp_path), _options(NameTakenPolicy.SUFFIX, library=library), _show_name()
    ).plan

    def no_resolve(self: Path, strict: bool = False) -> Path:
        raise AssertionError(f"resolved {self} while deriving")

    monkeypatch.setattr(Path, "resolve", no_resolve)
    left_out = derive_plan(plan, LeaveOut(_video(plan, "Disc A")))
    put_back = derive_plan(left_out, PutBack(_video(left_out, "Disc A")))
    monkeypatch.undo()

    assert put_back == plan
