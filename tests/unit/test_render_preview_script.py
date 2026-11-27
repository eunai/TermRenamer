"""``scripts/render_preview.py`` writes the README's preview screenshot as an SVG."""

from __future__ import annotations

import html
import importlib.util
import logging
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


def test_render_preview_writes_svg_of_the_preview_stage(tmp_path: Path) -> None:
    out = tmp_path / "preview.svg"

    _load_script().render_preview(out)

    svg = out.read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<svg")
    # Rich's SVG export writes each space as a non-breaking space entity.
    text = html.unescape(svg).replace("\xa0", " ")
    assert "● Preview" in text
    assert "Breaking Bad" in text and "ready" in text
    assert "1 Title · 4 videos" in text


def test_render_preview_leaves_the_root_logger_handlers_as_they_were(tmp_path: Path) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    before = list(root.handlers)
    try:
        _load_script().render_preview(tmp_path / "preview.svg")

        assert root.handlers == before
    finally:
        root.removeHandler(handler)
