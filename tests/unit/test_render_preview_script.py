"""``scripts/render_preview.py`` writes the README's preview screenshot as an SVG."""

from __future__ import annotations

import html
import importlib.util
import logging
import tempfile
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


def test_two_runs_write_the_same_file_with_no_path_of_this_machine(tmp_path: Path) -> None:
    script = _load_script()
    first = script.render_preview(tmp_path / "first.svg").read_bytes()
    second = script.render_preview(tmp_path / "second.svg").read_bytes()

    assert first == second
    text = html.unescape(first.decode("utf-8")).replace("\xa0", " ")
    temp = Path(tempfile.gettempdir())
    for machine_path in {str(temp), str(temp.resolve()), str(Path.home())}:
        assert machine_path not in text
    assert "TV Backups" in text and "breaking_bad_s01e01.mkv" in text
