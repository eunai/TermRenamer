"""The built wheel carries every file the app loads at start-up, and no unused dependency."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from conftest import REAL_ENVIRON

REPO_ROOT = Path(__file__).resolve().parents[2]

# What a clean export of the project needs to build: no caches, no build output.
_EXPORT = ("pyproject.toml", "README.md", "LICENSE", "src")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", "build", "dist")


def _requirement_name(requirement: str) -> str:
    name = re.split(r"[\s;<>=!~\[(]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv", path=REAL_ENVIRON.get("PATH"))
    if uv is None:
        pytest.skip("uv is not installed, so the wheel cannot be built")
    root = tmp_path_factory.mktemp("wheel-build")
    export = root / "export"
    export.mkdir()
    for name in _EXPORT:
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(source, export / name, ignore=_IGNORE)
        else:
            shutil.copy2(source, export / name)
    out_dir = root / "dist"
    result = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out_dir), str(export)],
        cwd=root,
        env=REAL_ENVIRON,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, f"uv build failed:\n{result.stdout}\n{result.stderr}"
    wheels = list(out_dir.glob("termrenamer-*.whl"))
    assert len(wheels) == 1, f"expected one wheel in {out_dir}, found {wheels}"
    return wheels[0]


def test_wheel_contains_the_tui_stylesheet_and_typing_marker(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        names = set(wheel.namelist())

    assert "termrenamer/tui/theme.tcss" in names
    assert "termrenamer/py.typed" in names


def test_wheel_metadata_does_not_require_the_unused_toml_writer(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        metadata_name = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")

    required = {
        _requirement_name(line.removeprefix("Requires-Dist:").strip())
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:")
    }
    assert "textual" in required
    assert "tomli-w" not in required
