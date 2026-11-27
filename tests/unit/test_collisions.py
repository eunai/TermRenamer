"""Collision and suffix behavior."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.collisions import allocate_destination


def test_suffix_when_destination_exists(tmp_path: Path) -> None:
    root = tmp_path
    dest_dir = root / "dest"
    dest_dir.mkdir()
    existing = dest_dir / "Show - S01E01 - Pilot.mkv"
    existing.write_bytes(b"x")

    source = root / "src.mkv"
    source.write_bytes(b"y")

    occupied: set[str] = set()
    desired = dest_dir / "Show - S01E01 - Pilot.mkv"
    got = allocate_destination(desired, source=source, occupied=occupied)
    assert got.name == "Show - S01E01 - Pilot (1).mkv"


def test_cascade_suffix(tmp_path: Path) -> None:
    root = tmp_path
    dest_dir = root / "dest"
    dest_dir.mkdir()
    (dest_dir / "Show - S01E01 - Pilot.mkv").write_bytes(b"a")
    (dest_dir / "Show - S01E01 - Pilot (1).mkv").write_bytes(b"b")

    s1 = root / "a.mkv"
    s2 = root / "b.mkv"
    s1.write_bytes(b"1")
    s2.write_bytes(b"2")
    occupied: set[str] = set()
    desired = dest_dir / "Show - S01E01 - Pilot.mkv"
    d1 = allocate_destination(desired, source=s1, occupied=occupied)
    d2 = allocate_destination(desired, source=s2, occupied=occupied)
    assert d1.name.endswith("(2).mkv")
    assert d2.name.endswith("(3).mkv")


def test_no_os_replace_in_apply_modules() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "termrenamer"
    text = (root / "core" / "apply.py").read_text(encoding="utf-8")
    assert "os.replace" not in text


def test_case_only_samefile_skips_suffix(tmp_path: Path) -> None:
    source = tmp_path / "show - s01e01 - pilot.mkv"
    source.write_bytes(b"x")
    desired = tmp_path / "Show - S01E01 - Pilot.mkv"

    # Where letter case is ignored the desired name is the source itself; elsewhere it is free.
    got = allocate_destination(desired, source=source, occupied=set())

    assert got == desired
