"""Which files a Plan holds: a source is told apart by its exact path, a link is planned
as itself, and the scan never enters a link or a junction (spec #16, section C)."""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest

from termrenamer.core.apply import apply_plan
from termrenamer.core.models import Candidate, EntryStatus, Plan, PlanOptions, ScanMode
from termrenamer.core.planning import LeaveOut, derive_plan, plan_queue
from termrenamer.core.queue import SourceQueue
from termrenamer.core.scan import scan

from .links import needs_symlinks, point_folder_at
from .test_plan_queue import TvStandIn


def _options(*, folder_rename: bool = False, season_folders: bool = False) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=None,
        folder_rename=folder_rename,
        season_folders=season_folders and folder_rename,
    )


def _provider() -> TvStandIn:
    return TvStandIn(
        shows={"show name": (Candidate(id="1", name="Show Name", year=2010),)},
        episodes={("1", 1, 1): "Pilot", ("1", 1, 2): "Second"},
    )


def _write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _folds_case(folder: Path) -> bool:
    """Whether the disk under ``folder`` takes two letter cases of a name for one name."""
    probe = folder / "case probe"
    probe.write_bytes(b"")
    try:
        return (folder / "CASE PROBE").exists()
    finally:
        probe.unlink()


def _needs_case_sensitive(folder: Path) -> None:
    if _folds_case(folder):
        pytest.skip("this disk does not tell letter case apart")


def _needs_case_folding(folder: Path) -> None:
    if not _folds_case(folder):
        pytest.skip("this disk tells letter case apart")


def _sources(plan: Plan) -> list[str]:
    return [str(e.source) for e in plan.entries]


# --------------------------------------------------------------------------
# A source is told apart by its exact recorded path.
# --------------------------------------------------------------------------


def test_two_folders_whose_names_differ_only_in_letter_case_both_keep_their_videos(
    tmp_path: Path,
) -> None:
    _needs_case_sensitive(tmp_path)
    source = tmp_path.resolve() / "Backups"
    upper = _write(source / "Disc" / "Show.Name.S01E01.mkv", b"upper")
    lower = _write(source / "disc" / "Show.Name.S01E01.mkv", b"lower")

    plan = plan_queue([source], _options(), _provider()).plan

    assert sorted(_sources(plan)) == sorted([str(upper), str(lower)])
    assert all(e.status is not EntryStatus.LEFT_OUT for e in plan.entries)


def test_a_sidecar_pairs_with_the_video_in_its_own_folder_only(tmp_path: Path) -> None:
    _needs_case_sensitive(tmp_path)
    source = tmp_path.resolve() / "Backups"
    _write(source / "Disc" / "Show.Name.S01E01.mkv")
    own_video = _write(source / "disc" / "Show.Name.S01E01.mp4")
    sidecar = _write(source / "disc" / "Show.Name.S01E01.srt")

    plan = plan_queue([source], _options(), _provider()).plan

    [entry] = [e for e in plan.entries if str(e.source) == str(sidecar)]
    assert entry.video is not None
    assert str(entry.video) == str(own_video)


def test_a_folder_whose_name_differs_from_the_target_only_in_letter_case_is_another_folder(
    tmp_path: Path,
) -> None:
    _needs_case_sensitive(tmp_path)
    source = tmp_path.resolve() / "Backups"
    old = source / "show name"
    _write(old / "Show.Name.S01E01.mkv")
    notes = _write(old / "notes.txt")
    options = _options(folder_rename=True)

    plan = plan_queue([source], options, _provider()).plan

    target = source / "Show Name"
    assert [(str(s.source), str(s.destination)) for s in plan.stragglers] == [
        (str(notes), str(target / "notes.txt"))
    ]
    outcome = apply_plan(plan, confirmed=True)
    assert sorted(os.listdir(target)) == ["Show Name - S01E01 - Pilot.mkv", "notes.txt"]
    assert not old.exists()
    assert [str(f) for f in outcome.folders_removed] == [str(old)]


def test_a_folder_the_target_names_in_another_letter_case_is_that_folder_on_a_disk_that_folds_case(
    tmp_path: Path,
) -> None:
    _needs_case_folding(tmp_path)
    source = tmp_path.resolve() / "Backups"
    old = source / "show name"
    _write(old / "Show.Name.S01E01.mkv")
    _write(old / "notes.txt")

    plan = plan_queue([source], _options(folder_rename=True), _provider()).plan

    [video] = plan.videos
    assert video.destination is not None
    assert video.destination.name == "Show Name - S01E01 - Pilot.mkv"
    assert plan.stragglers == ()


def test_a_file_queued_under_another_spelling_of_a_queued_folder_is_planned_once(
    tmp_path: Path,
) -> None:
    _needs_case_folding(tmp_path)
    folder = tmp_path.resolve() / "Backups" / "Show Name"
    video = _write(folder / "Show.Name.S01E01.mkv")
    _write(folder / "Show.Name.S01E01.srt")
    other_spelling = tmp_path.resolve() / "backups" / "show name" / "show.name.s01e01.MKV"

    plan = plan_queue([folder, other_spelling], _options(), _provider()).plan

    assert _sources(plan) == [str(video), str(folder / "Show.Name.S01E01.srt")]
    assert [str(e.root) for e in plan.entries] == [str(folder)] * 2


def test_a_file_queued_in_another_unicode_form_of_a_queued_folder_is_planned_once(
    tmp_path: Path,
) -> None:
    composed = unicodedata.normalize("NFC", "Café")
    folder = tmp_path.resolve() / composed
    video = _write(folder / "Show.Name.S01E01.mkv")
    decomposed = tmp_path.resolve() / unicodedata.normalize("NFD", composed)
    if not (decomposed / "Show.Name.S01E01.mkv").exists():
        pytest.skip("this disk tells Unicode forms of a name apart")

    plan = plan_queue([folder, decomposed / "Show.Name.S01E01.mkv"], _options(), _provider()).plan

    assert len(plan.entries) == 1
    assert os.path.samefile(plan.entries[0].source, video)


# --------------------------------------------------------------------------
# A link is planned as itself; the scan never enters a link or a junction.
# --------------------------------------------------------------------------


def test_a_queued_video_that_is_a_symbolic_link_is_planned_as_the_link(tmp_path: Path) -> None:
    needs_symlinks(tmp_path)
    elsewhere = _write(tmp_path / "Elsewhere" / "Show.Name.S01E01.mkv", b"real")
    folder = tmp_path / "Backups"
    folder.mkdir()
    link = folder / "Show.Name.S01E02.mkv"
    link.symlink_to(elsewhere)

    queue = SourceQueue()
    queued = queue.add(link)
    plan = plan_queue(queue.sources, _options(), _provider()).plan

    assert str(queued) == str(folder.resolve() / link.name)
    [entry] = plan.entries
    assert str(entry.source) == str(folder.resolve() / link.name)
    assert entry.destination is not None
    assert str(entry.destination) == str(folder.resolve() / "Show Name - S01E02 - Second.mkv")


@pytest.mark.parametrize("kind", ["symbolic link", "folder link"])
def test_the_scan_never_enters_a_link_to_a_folder_of_videos(tmp_path: Path, kind: str) -> None:
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "Show.Name.S01E02.mkv")
    source = tmp_path / "Backups"
    own = _write(source / "Show.Name.S01E01.mkv")
    if kind == "symbolic link":
        needs_symlinks(tmp_path)
        (source / "Linked").symlink_to(elsewhere, target_is_directory=True)
    else:
        # A junction on Windows, which needs no privilege; a symbolic link elsewhere.
        point_folder_at(source / "Linked", elsewhere)

    found = scan(root=source)
    plan = plan_queue([source], _options(), _provider()).plan

    assert [f.path.name for f in found] == [own.name]
    assert [e.source.name for e in plan.entries] == [own.name]


def test_a_video_reached_through_a_folder_link_inside_a_source_is_never_planned(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "Show.Name.S01E02.mkv")
    source = tmp_path / "Backups"
    _write(source / "Show.Name.S01E01.mkv")
    point_folder_at(source / "Linked", elsewhere)

    plan = plan_queue([source], _options(folder_rename=True), _provider()).plan

    assert [e.source.name for e in plan.entries] == ["Show.Name.S01E01.mkv"]
    left_out = derive_plan(plan, LeaveOut(plan.videos[0]))
    assert [e.source.name for e in left_out.entries] == ["Show.Name.S01E01.mkv"]


def _organised(tmp_path: Path, file_name: str) -> tuple[Path, Path]:
    """An organised library listed as ``Library`` and typed ``library``, as a person may
    type both the queued folder and the Destination root on a disk that folds case."""
    listed = tmp_path.resolve() / "Library"
    video = _write(listed / "Show Name" / "Season 01" / file_name)
    return video, tmp_path.resolve() / "library"


def _library_options(destination_root: Path) -> PlanOptions:
    return PlanOptions(
        mode=ScanMode.TV,
        provider_id="tmdb",
        destination_root=destination_root,
        folder_rename=True,
        season_folders=True,
    )


def test_a_file_that_has_its_name_under_another_spelling_of_its_folders_keeps_it(
    tmp_path: Path,
) -> None:
    _needs_case_folding(tmp_path)
    video, typed = _organised(tmp_path, "Show Name - S01E01 - Pilot.mkv")
    queue = SourceQueue()
    queue.add(typed)

    plan = plan_queue(queue.sources, _library_options(typed), _provider()).plan
    [entry] = plan.entries
    assert (entry.status, entry.has_its_name) == (EntryStatus.READY, True)

    outcome = apply_plan(plan, confirmed=True)
    assert [r.status.value for r in outcome.results] == ["unchanged"]
    assert os.listdir(video.parent) == [video.name]


def test_a_case_only_rename_under_another_spelling_of_its_folders_is_made_in_its_folder(
    tmp_path: Path,
) -> None:
    _needs_case_folding(tmp_path)
    video, typed = _organised(tmp_path, "show name - s01e01 - pilot.mkv")

    plan = plan_queue([typed], _library_options(typed), _provider()).plan
    [entry] = plan.entries
    assert entry.status is EntryStatus.READY
    assert entry.destination is not None
    assert str(entry.destination) == str(video.parent / "Show Name - S01E01 - Pilot.mkv")

    apply_plan(plan, confirmed=True)
    assert os.listdir(video.parent) == ["Show Name - S01E01 - Pilot.mkv"]


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="a folder that can be entered but not listed needs POSIX permissions and no root",
)
def test_a_file_source_whose_folder_cannot_be_listed_is_planned_alone(tmp_path: Path) -> None:
    folder = tmp_path.resolve() / "Backups"
    video = _write(folder / "Show.Name.S01E01.mkv")
    _write(folder / "Show.Name.S01E01.srt")
    folder.chmod(0o300)
    try:
        plan = plan_queue([video], _options(), _provider()).plan
    finally:
        folder.chmod(0o700)

    assert _sources(plan) == [str(video)]


def test_a_queued_folder_that_became_a_link_before_the_build_is_not_entered(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "Elsewhere"
    _write(elsewhere / "Show.Name.S01E02.mkv")
    folder = tmp_path / "Backups"
    _write(folder / "Show.Name.S01E01.mkv")
    queue = SourceQueue()
    queued = queue.add(folder)
    (folder / "Show.Name.S01E01.mkv").unlink()
    folder.rmdir()
    point_folder_at(folder, elsewhere)

    build = plan_queue(queue.sources, _options(), _provider())

    assert build.plan.entries == ()
    [message] = build.messages
    assert str(queued) in message and "link" in message


def test_a_source_folder_gone_after_the_build_turns_its_stragglers_off_in_a_derive(
    tmp_path: Path,
) -> None:
    _needs_case_sensitive(tmp_path)
    source = tmp_path.resolve() / "Backups"
    old = source / "show name"
    _write(old / "Show.Name.S01E01.mkv")
    _write(old / "Show.Name.S01E02.mkv")
    _write(old / "notes.txt")
    plan = plan_queue([source], _options(folder_rename=True), _provider()).plan
    assert len(plan.stragglers) == 1
    for child in list(old.iterdir()):
        child.unlink()
    old.rmdir()

    left_out = derive_plan(plan, LeaveOut(plan.videos[0]))

    assert left_out.stragglers == ()
