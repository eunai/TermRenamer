"""Apply and a left out file: it is never touched, and it is counted as left out, not skipped."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyStatus,
    Candidate,
    EntryStatus,
    Plan,
    PlanOptions,
    ScanMode,
)
from termrenamer.core.planning import LeaveOut, derive_plan, plan_queue
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.core.title_rows import (
    AppliedCounts,
    PlanCounts,
    sidecars_skipped_alone,
    title_rows,
)

from .test_plan_leave_out import TvStandIn


def _provider() -> TvStandIn:
    return TvStandIn(
        shows={"show name": (Candidate(id="1", name="Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )


def _plan(folder: Path, *, library: Path | None = None) -> Plan:
    options = PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=library,
        folder_rename=library is not None,
        season_folders=False,
        name_taken=NameTakenPolicy.SKIP,
    )
    return plan_queue([folder], options, _provider()).plan


def _show(tmp_path: Path) -> Path:
    """The Pilot with two Sidecars, and a second episode."""
    folder = tmp_path / "Backups"
    folder.mkdir()
    (folder / "Show.Name.S01E01.mkv").write_bytes(b"pilot")
    (folder / "Show.Name.S01E01.srt").write_bytes(b"subs")
    (folder / "Show.Name.S01E01.nfo").write_bytes(b"info")
    (folder / "Show.Name.S01E02.mkv").write_bytes(b"second")
    return folder


def _contents(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def _left_out_pilot(plan: Plan) -> Plan:
    pilot = next(v for v in plan.videos if v.episode == 1)
    return derive_plan(plan, LeaveOut(pilot.source))


def test_apply_never_touches_a_left_out_video_or_its_two_sidecars(tmp_path: Path) -> None:
    folder = _show(tmp_path)
    plan = _left_out_pilot(_plan(folder))

    results = apply_plan(plan, confirmed=True)

    assert _contents(folder) == {
        "Show.Name.S01E01.mkv": b"pilot",
        "Show.Name.S01E01.nfo": b"info",
        "Show.Name.S01E01.srt": b"subs",
        "Show Name - S01E02 - Second.mkv": b"second",
    }
    by_name = {r.source.name: (r.status, r.reason) for r in results}
    assert by_name == {
        "Show.Name.S01E01.mkv": (ApplyStatus.LEFT_OUT, "left out"),
        "Show.Name.S01E01.nfo": (ApplyStatus.LEFT_OUT, "left out"),
        "Show.Name.S01E01.srt": (ApplyStatus.LEFT_OUT, "left out"),
        "Show.Name.S01E02.mkv": (ApplyStatus.RENAMED, "ok"),
    }
    assert AppliedCounts.of(plan, results) == AppliedCounts(
        renamed=1, unchanged=0, skipped=0, failed=0, left_out=1
    )


def test_with_folder_rename_a_left_out_file_stays_in_its_folder(tmp_path: Path) -> None:
    folder = _show(tmp_path)
    library = tmp_path / "Library"
    plan = _left_out_pilot(_plan(folder, library=library))

    apply_plan(plan, confirmed=True)

    # The second episode moved out; the left out Pilot is not merged after it.
    assert sorted(_contents(folder)) == [
        "Show.Name.S01E01.mkv",
        "Show.Name.S01E01.nfo",
        "Show.Name.S01E01.srt",
    ]
    second = Path("Show Name") / "Show Name - S01E02 - Second.mkv"
    assert sorted(_contents(library)) == [str(second)]


def test_the_plan_counts_left_out_videos_apart_and_no_left_out_sidecar_is_skipped_alone(
    tmp_path: Path,
) -> None:
    plan = _left_out_pilot(_plan(_show(tmp_path)))

    counts = PlanCounts.of(plan)
    assert (counts.videos, counts.to_rename, counts.ready, counts.left_out) == (2, 1, 1, 1)
    assert sidecars_skipped_alone(plan) == ()


def test_a_title_is_left_out_only_when_every_file_of_it_is(tmp_path: Path) -> None:
    plan = _plan(_show(tmp_path))
    one_out = _left_out_pilot(plan)
    second = next(v for v in plan.videos if v.episode == 2)
    both_out = derive_plan(one_out, LeaveOut(second.source))

    assert [row.status for row in title_rows(one_out)] == [EntryStatus.READY]
    assert [row.status for row in title_rows(both_out)] == [EntryStatus.LEFT_OUT]


def test_a_title_with_a_file_of_no_match_says_no_match_before_left_out(tmp_path: Path) -> None:
    folder = _show(tmp_path)
    (folder / "Show.Name.S01E09.mkv").write_bytes(b"nine")
    plan = _plan(folder)
    for episode in (1, 2):
        video = next(v for v in plan.videos if v.episode == episode)
        plan = derive_plan(plan, LeaveOut(video.source))

    assert [row.status for row in title_rows(plan)] == [EntryStatus.NO_MATCH]
