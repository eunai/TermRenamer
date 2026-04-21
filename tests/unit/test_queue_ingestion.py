"""Phase 2 queue ingestion: fspicker callbacks, ``_refresh_source_tree``, clear.

These tests exercise the public queue surface added in Phase 2 without
pushing the actual ``SelectDirectory`` / ``FileOpen`` modals — we call the
callbacks directly so the tests remain deterministic and independent of the
``textual-fspicker`` version.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Tree

from termrenamer.api.tmdb import StaticFilmMetadataProvider, StaticTvMetadataProvider
from termrenamer.core.models import EpisodeMetadata, MovieMetadata
from termrenamer.tui.app import TermRenamerApp
from termrenamer.wiring import PlanningWiring


def _wiring() -> PlanningWiring:
    tv = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="Pilot"),
        },
    )
    film = StaticFilmMetadataProvider(
        _mapping={("show name", None): MovieMetadata(title="Show Name", year=2020)},
    )
    return PlanningWiring(tv_tmdb=tv, tv_tvdb=None, film=film, film_omdb=None)


@pytest.mark.asyncio
async def test_source_tree_shows_empty_hint_on_mount() -> None:
    """Mount wires an empty-state leaf into ``#source-tree`` before any queue actions."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one("#source-tree", Tree)
        children = list(tree.root.children)
        assert len(children) == 1
        assert "empty" in str(children[0].label).lower()


@pytest.mark.asyncio
async def test_on_folder_picked_appends_to_queue_and_refreshes(tmp_path: Path) -> None:
    """Folder-picker callback pushes onto ``_queue`` and rebuilds the source tree."""
    (tmp_path / "a.mkv").write_bytes(b"x")
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        assert app._queue == [tmp_path.resolve()]
        tree = app.query_one("#source-tree", Tree)
        labels = [str(c.label) for c in tree.root.children]
        assert labels, "Tree should have at least one entry after queueing a folder"
        assert "empty" not in labels[0].lower()


@pytest.mark.asyncio
async def test_on_file_picked_appends_to_queue(tmp_path: Path) -> None:
    """File-picker callback records the exact path (not its parent) on the queue."""
    f = tmp_path / "clip.mkv"
    f.write_bytes(b"x")
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_file_picked(f)
        await pilot.pause()
        assert app._queue == [f.resolve()]


@pytest.mark.asyncio
async def test_on_folder_picked_none_is_noop() -> None:
    """Cancelling the picker (``None``) must not mutate state."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(None)
        app._on_file_picked(None)
        await pilot.pause()
        assert app._queue == []


@pytest.mark.asyncio
async def test_clear_queue_resets_state(tmp_path: Path) -> None:
    """``clear`` empties ``_queue`` and clears derived plan state."""
    (tmp_path / "a.mkv").write_bytes(b"x")
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(tmp_path)
        await pilot.pause()
        assert app._queue
        app._clear_queue()
        await pilot.pause()
        assert app._queue == []
        tree = app.query_one("#source-tree", Tree)
        labels = [str(c.label) for c in tree.root.children]
        assert labels and "empty" in labels[0].lower()


@pytest.mark.asyncio
async def test_on_add_source_choice_routes_to_folder_and_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AddSourceQuickPick`` result dispatches to the right picker opener."""
    app = TermRenamerApp(wiring=_wiring())
    calls: list[str] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "_open_folder_picker", lambda: calls.append("folder"))
        monkeypatch.setattr(app, "_open_file_picker", lambda: calls.append("file"))

        app._on_add_source_choice("folder")
        app._on_add_source_choice("file")
        app._on_add_source_choice(None)
        await pilot.pause()

    assert calls == ["folder", "file"]


@pytest.mark.asyncio
async def test_clear_queue_on_empty_logs_without_error() -> None:
    """Clearing an already-empty queue is a no-op (not an error)."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._clear_queue()
        await pilot.pause()
        assert app._queue == []


@pytest.mark.asyncio
async def test_append_to_queue_oserror_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``OSError`` from ``Path.resolve`` is caught and reported, not raised."""
    app = TermRenamerApp(wiring=_wiring())

    class _Fail(Path):
        def resolve(self, strict: bool = False) -> Path:  # type: ignore[override]
            raise OSError("cannot stat")

    async with app.run_test() as pilot:
        await pilot.pause()
        bad = _Fail(str(tmp_path))
        app._append_to_queue(bad, kind="folder")
        await pilot.pause()
    assert app._queue == []


@pytest.mark.asyncio
async def test_build_plan_without_queue_logs_warning() -> None:
    """Pressing Build plan with an empty queue surfaces a warning, not a crash."""
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
    assert app.current_plan is None


@pytest.mark.asyncio
async def test_build_plan_for_queued_file_excludes_sibling_videos(tmp_path: Path) -> None:
    """A queued *file* includes only that video (not unpicked siblings in the folder)."""
    tv = StaticTvMetadataProvider(
        _mapping={
            ("show name", 1, 1): EpisodeMetadata(show_title="Show Name", episode_title="E1"),
            ("show name", 1, 2): EpisodeMetadata(show_title="Show Name", episode_title="E2"),
        },
    )
    wiring = PlanningWiring(
        tv_tmdb=tv,
        tv_tvdb=None,
        film=StaticFilmMetadataProvider(_mapping={}),
        film_omdb=None,
    )
    (tmp_path / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (tmp_path / "Show.Name.S01E02.mkv").write_bytes(b"b")
    app = TermRenamerApp(wiring=wiring)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_file_picked(tmp_path / "Show.Name.S01E01.mkv")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
    assert app.current_plan is not None
    assert len(app.current_plan.entries) == 1


@pytest.mark.asyncio
async def test_build_plan_merges_two_queued_folders(tmp_path: Path) -> None:
    """Phase 3: two queued directories produce one merged plan with two operations."""
    a = tmp_path / "lib_a"
    b = tmp_path / "lib_b"
    a.mkdir()
    b.mkdir()
    (a / "Show.Name.S01E01.mkv").write_bytes(b"a")
    (b / "Show.Name.S01E01.mkv").write_bytes(b"b")
    app = TermRenamerApp(wiring=_wiring())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_folder_picked(a)
        app._on_folder_picked(b)
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
    assert app.current_plan is not None
    assert len(app.current_plan.entries) == 2
