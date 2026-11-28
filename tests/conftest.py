"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from termrenamer.api.base import FilmMetadataProvider, TvMetadataProvider
from termrenamer.core.models import Plan, PlanOptions, ScanMode
from termrenamer.core.planning import plan_queue

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
    cache_home: Path
    local_appdata: Path

    @property
    def user_settings_file(self) -> Path:
        """The user settings file the app reads on the running platform, in these folders.

        Under ``appdata`` on Windows, under ``config_home`` everywhere else. Built from the
        fixture's folders, not from the app's resolver, so tests stay independent of it.
        """
        base = self.appdata if sys.platform == "win32" else self.config_home
        return base / "termrenamer" / ".env"


@pytest.fixture(autouse=True)
def isolated_settings_dirs(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[IsolatedDirs]:
    """Point every per-user folder and the working folder at temporary locations.

    No test reads the developer's real user settings file, a ``.env`` in the folder
    pytest was started from, or a ``TERMRENAMER_*`` variable from the developer's shell,
    and none reaches the real per-user cache folder that holds Poster files.
    """
    root = tmp_path_factory.mktemp("isolated")
    dirs = IsolatedDirs(
        home=root / "home",
        config_home=root / "home" / ".config",
        appdata=root / "home" / "AppData" / "Roaming",
        workdir=root / "work",
        cache_home=root / "home" / ".cache",
        local_appdata=root / "home" / "AppData" / "Local",
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
    monkeypatch.setenv("XDG_CACHE_HOME", str(dirs.cache_home))
    monkeypatch.setenv("LOCALAPPDATA", str(dirs.local_appdata))
    monkeypatch.chdir(dirs.workdir)
    yield dirs


def plan_folder(
    root: Path,
    mode: ScanMode,
    provider: TvMetadataProvider | FilmMetadataProvider,
    *,
    destination_root: Path | None = None,
    folder_rename: bool = True,
    season_folders: bool = True,
    provider_id: str = "tmdb",
) -> Plan:
    """Plan one folder Source through the core entry point, as the app builds a Plan."""
    options = PlanOptions(
        mode=mode,
        provider_id=provider_id,
        destination_root=destination_root if folder_rename else None,
        folder_rename=folder_rename,
        season_folders=mode is ScanMode.TV and folder_rename and season_folders,
    )
    return plan_queue([root], options, provider).plan
