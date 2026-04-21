"""Tests for recursive directory scanning."""

from __future__ import annotations

from pathlib import Path

from termrenamer.core.models import FileKind
from termrenamer.core.scan import scan


def test_scan_discovers_media_and_sidecars(tmp_path: Path) -> None:
    root = tmp_path
    (root / "ShowA" / "Season 01").mkdir(parents=True)
    (root / "ShowA" / "Season 01" / "ShowA.S01E01.720p.mkv").write_bytes(b"v")
    (root / "ShowA" / "Season 01" / "ShowA.S01E01.srt").write_text("sub", encoding="utf-8")
    (root / "ShowA" / "Season 01" / "notes.txt").write_text("n", encoding="utf-8")
    (root / "ShowB").mkdir()
    (root / "ShowB" / "ShowB.S02E03.mp4").write_bytes(b"v")

    found = scan(root=root)
    kinds = {f.path.name: f.kind for f in found}
    assert set(kinds) == {"ShowA.S01E01.720p.mkv", "ShowA.S01E01.srt", "ShowB.S02E03.mp4"}
    assert kinds["ShowA.S01E01.720p.mkv"] is FileKind.VIDEO
    assert kinds["ShowA.S01E01.srt"] is FileKind.SIDECAR
    assert "notes.txt" not in kinds
