"""``scripts/render_preview.py`` writes the README's preview screenshot as an SVG."""

from __future__ import annotations

import html
import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "render_preview.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_preview", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_preview_writes_svg_with_episode_one_destination(tmp_path: Path) -> None:
    out = tmp_path / "preview.svg"

    _load_script().render_preview(out)

    svg = out.read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<svg")
    # Rich's SVG export writes each space as a non-breaking space entity.
    text = html.unescape(svg).replace("\xa0", " ")
    assert "Breaking Bad - S01E01 - Pilot.mkv" in text
