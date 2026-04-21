"""End-to-end film rename with stub film provider."""

from __future__ import annotations

from pathlib import Path

from termrenamer.api.tmdb import StaticFilmMetadataProvider
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import MovieMetadata, ScanMode
from termrenamer.core.planning import build_rename_plan


def test_film_scan_plan_apply(tmp_path: Path) -> None:
    (tmp_path / "The.Matrix.1999.1080p.mkv").write_bytes(b"v")
    provider = StaticFilmMetadataProvider(
        _mapping={
            ("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999),
        },
    )
    plan = build_rename_plan(root=tmp_path, mode=ScanMode.FILM, provider=provider)
    assert len(plan.entries) == 1
    dest = plan.entries[0].destination
    assert "The Matrix (1999)" in str(dest)
    apply_plan(plan=plan, confirmed=True)
    assert dest.exists()


def test_film_dest_root_moves_and_prunes_empty_source_dir(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    dest_root = tmp_path / "dst"
    nest = src_root / "Nest"
    vid = nest / "The.Matrix.1999.1080p.mkv"
    nest.mkdir(parents=True)
    vid.write_bytes(b"v")
    provider = StaticFilmMetadataProvider(
        _mapping={("the matrix", 1999): MovieMetadata(title="The Matrix", year=1999)},
    )
    plan = build_rename_plan(
        root=src_root,
        mode=ScanMode.FILM,
        provider=provider,
        film_dest_root=dest_root,
    )
    apply_plan(plan=plan, confirmed=True)
    assert not vid.exists()
    assert (dest_root / "The Matrix (1999)" / "The Matrix (1999).mkv").exists()
    assert not nest.exists()
