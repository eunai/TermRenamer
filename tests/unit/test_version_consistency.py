"""The version copies match the newest CHANGELOG.md version heading.

``CHANGELOG.md`` is the version (``docs/agents/versioning.md``, "Where the version
lives"); ``pyproject.toml`` and ``termrenamer.__version__`` are copies of it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import termrenamer

REPO_ROOT = Path(__file__).resolve().parents[2]

# The first ``## [x.y.z]`` heading; ``## [Unreleased]`` never matches.
_VERSION_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def newest_changelog_version(text: str) -> str:
    match = _VERSION_HEADING.search(text)
    assert match is not None, "CHANGELOG.md has no ## [x.y.z] version heading"
    return match.group(1)


def test_newest_changelog_version_skips_unreleased() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n## [0.3.1] - 2026-01-02\n\n## [0.3.0] - 2026-01-01\n"

    assert newest_changelog_version(text) == "0.3.1"


def test_version_copies_match_newest_changelog_heading() -> None:
    changelog = newest_changelog_version((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)["project"]["version"]

    assert {
        "pyproject.toml": pyproject,
        "termrenamer.__version__": termrenamer.__version__,
    } == {
        "pyproject.toml": changelog,
        "termrenamer.__version__": changelog,
    }
