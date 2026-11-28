"""Links the tests make on every system: a folder pointed elsewhere, and symbolic links
where the system allows them."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def point_folder_at(link: Path, target: Path) -> None:
    """Make ``link`` a folder that points to ``target``: a junction on Windows, which
    needs no privilege, and a symbolic link elsewhere."""
    if sys.platform == "win32":
        import _winapi  # Windows only

        _winapi.CreateJunction(str(target.absolute()), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def needs_symlinks(folder: Path) -> None:
    """Skip the test when this system makes no symbolic link in ``folder``: Windows makes
    one only with a privilege or in Developer Mode."""
    probe = folder / "symbolic link probe"
    try:
        probe.symlink_to("missing target")
    except OSError as exc:
        pytest.skip(f"this system makes no symbolic links without a privilege: {exc}")
    probe.unlink()
