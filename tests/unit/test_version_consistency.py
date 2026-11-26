"""The version copies match the newest CHANGELOG.md version heading.

``CHANGELOG.md`` is the version (``docs/agents/versioning.md``, "Where the version
lives"); ``pyproject.toml``, ``termrenamer.__version__`` and the README's Version badge
are copies of it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import termrenamer

REPO_ROOT = Path(__file__).resolve().parents[2]

# The first ``## [x.y.z]`` heading; ``## [Unreleased]`` never matches.
_VERSION_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def newest_changelog_version(text: str) -> str:
    match = _VERSION_HEADING.search(text)
    assert match is not None, "CHANGELOG.md has no ## [x.y.z] version heading"
    return match.group(1)


# A Shields.io badge whose alt text is ``Version``: ``[![Version](.../badge/version-x.y.z-...)``.
_VERSION_BADGE = re.compile(
    r"!\[Version\]\(https://img\.shields\.io/badge/version-(\d+\.\d+\.\d+)-",
)


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def readme_badge_version(text: str) -> str:
    match = _VERSION_BADGE.search(_HTML_COMMENT.sub("", text))
    assert match is not None, "README.md has no Version badge"
    return match.group(1)


def test_newest_changelog_version_skips_unreleased() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n## [0.3.1] - 2026-01-02\n\n## [0.3.0] - 2026-01-01\n"

    assert newest_changelog_version(text) == "0.3.1"


def test_readme_badge_version_reads_the_version_badge() -> None:
    text = (
        "# App\n\n"
        "[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)\n"
        "[![Version](https://img.shields.io/badge/version-0.4.2-blue?style=flat-square)]"
        "(./pyproject.toml)\n"
    )

    assert readme_badge_version(text) == "0.4.2"


def test_readme_badge_version_fails_without_a_version_badge() -> None:
    text = "# App\n\n[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)\n"

    with pytest.raises(AssertionError, match="no Version badge"):
        readme_badge_version(text)


def test_readme_badge_version_ignores_a_commented_out_badge() -> None:
    text = (
        "# App\n\n<!--\n"
        "[![Version](https://img.shields.io/badge/version-0.4.2-blue)](./pyproject.toml)\n"
        "-->\n"
    )

    with pytest.raises(AssertionError, match="no Version badge"):
        readme_badge_version(text)


def test_version_copies_match_newest_changelog_heading() -> None:
    changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    changelog_version = newest_changelog_version(changelog_text)
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject_version = tomllib.load(fh)["project"]["version"]
    readme_version = readme_badge_version((REPO_ROOT / "README.md").read_text(encoding="utf-8"))

    assert {
        "pyproject.toml": pyproject_version,
        "termrenamer.__version__": termrenamer.__version__,
        "README.md Version badge": readme_version,
    } == {
        "pyproject.toml": changelog_version,
        "termrenamer.__version__": changelog_version,
        "README.md Version badge": changelog_version,
    }
