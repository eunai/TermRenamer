"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

# The environment pytest started with, before any test isolation; for subprocesses
# that need the developer's real tool caches (such as the wheel build).
REAL_ENVIRON: dict[str, str] = dict(os.environ)


@dataclass(frozen=True, slots=True)
class IsolatedDirs:
    """Temporary folders that stand in for the person's home and working folder."""

    home: Path
    config_home: Path
    appdata: Path
    workdir: Path


@pytest.fixture(autouse=True)
def isolated_settings_dirs(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[IsolatedDirs]:
    """Point every per-user folder and the working folder at temporary locations.

    No test reads the developer's real user settings file, a ``.env`` in the folder
    pytest was started from, or a ``TERMRENAMER_*`` variable from the developer's shell.
    """
    root = tmp_path_factory.mktemp("isolated")
    dirs = IsolatedDirs(
        home=root / "home",
        config_home=root / "home" / ".config",
        appdata=root / "home" / "AppData" / "Roaming",
        workdir=root / "work",
    )
    for folder in (dirs.home, dirs.workdir):
        folder.mkdir(parents=True)
    for name in list(os.environ):
        if name.startswith("TERMRENAMER_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(dirs.home))
    monkeypatch.setenv("USERPROFILE", str(dirs.home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(dirs.config_home))
    monkeypatch.setenv("APPDATA", str(dirs.appdata))
    monkeypatch.chdir(dirs.workdir)
    yield dirs
