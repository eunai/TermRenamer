"""Collision and suffix behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from termrenamer.core.collisions import allocate_destination, claim_name
from termrenamer.core.paths import claim_key
from termrenamer.core.policies import NameTakenPolicy

from .links import point_folder_at


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


def test_under_skip_a_claim_is_the_wanted_name_or_none_whatever_appears_between_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s")
    desired = tmp_path / "new.mkv"
    looks: list[Path] = []
    real_exists = Path.exists

    def exists_then_appears(self: Path, *, follow_symlinks: bool = True) -> bool:
        # A file appears at the wanted name just after the first look at it.
        found = real_exists(self, follow_symlinks=follow_symlinks)
        if self == desired and not looks:
            looks.append(self)
            desired.write_bytes(b"appeared")
        return found

    monkeypatch.setattr(Path, "exists", exists_then_appears)
    got = claim_name(desired, source=source, occupied=set(), policy=NameTakenPolicy.SKIP)
    monkeypatch.undo()

    assert got in (desired, None)


def test_names_that_are_canonically_equal_once_case_folded_have_one_claim_key() -> None:
    # U+0345 folds to a base iota, so folding before normalising splits these two.
    assert claim_key(Path("\u03b1\u0345\u0300.txt")) == claim_key(Path("\u03b1\u0300\u0345.txt"))
    assert claim_key(Path("Caf\u00e9.jpg")) == claim_key(Path("cafe\u0301.JPG"))
    # Windows upper-cases each letter to compare names: dotless i is the same name as I.
    assert claim_key(Path("\u0131.mkv")) == claim_key(Path("I.mkv")) == claim_key(Path("i.mkv"))
    assert claim_key(Path("a.mkv")) != claim_key(Path("b.mkv"))


def test_a_second_claim_of_one_unicode_name_gets_a_number(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s")
    occupied: set[str] = set()
    first = claim_name(
        tmp_path / "\u03b1\u0345\u0300.mkv",
        source=source,
        occupied=occupied,
        policy=NameTakenPolicy.SUFFIX,
    )
    second = claim_name(
        tmp_path / "\u03b1\u0300\u0345.mkv",
        source=source,
        occupied=occupied,
        policy=NameTakenPolicy.SUFFIX,
    )
    assert str(first) == str(tmp_path / "\u03b1\u0345\u0300.mkv")
    assert str(second) == str(tmp_path / "\u03b1\u0300\u0345 (1).mkv")


def test_a_name_claimed_through_a_folder_that_points_elsewhere_is_taken_at_that_folder(
    tmp_path: Path,
) -> None:
    real = tmp_path / "Films"
    real.mkdir()
    alias = tmp_path / "Films link"
    point_folder_at(alias, real)
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s")
    occupied: set[str] = set()

    first = claim_name(
        alias / "Film (2000).mkv", source=source, occupied=occupied, policy=NameTakenPolicy.SUFFIX
    )
    second = claim_name(
        real / "Film (2000).mkv", source=source, occupied=occupied, policy=NameTakenPolicy.SKIP
    )
    third = allocate_destination(real / "Film (2000).mkv", source=source, occupied=occupied)

    assert str(first) == str(alias / "Film (2000).mkv")
    assert second is None
    assert str(third) == str(real / "Film (2000) (1).mkv")
