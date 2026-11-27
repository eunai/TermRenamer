"""The session's settings owner: one place for the batch's settings, outside the screen.

It holds the values loaded at start with the session's changes on top, and yields
the plan options a Plan is built with. A change lasts for the session; the user
settings file is never written.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from termrenamer.app_bootstrap import Settings
from termrenamer.core.models import PlanOptions, ScanMode
from termrenamer.util.errors import ValidationError

PlanSettingListener = Callable[[str], None]
"""Called with a setting's name after a change to a setting a Plan is built with."""


class SettingsLockedError(ValidationError):
    """A setting was changed while a Plan is being built or applied."""


class SessionSettings:
    """The effective settings of this session.

    Every setting here is one a Plan is built with: Mode, Provider, the two
    Destination roots, Folder rename and Season folder. A change to any of them is
    reported to the listeners, so that a Plan built with the old value can be
    discarded. While locked (a Plan is being built or applied) every change is
    refused with :class:`SettingsLockedError`.
    """

    def __init__(self, loaded: Settings | None = None) -> None:
        self._mode = ScanMode.TV
        self._provider_id = "tmdb"
        self._destination_roots: dict[ScanMode, Path | None] = {
            ScanMode.TV: loaded.tv_dest_folder if loaded is not None else None,
            ScanMode.FILM: loaded.film_dest_folder if loaded is not None else None,
        }
        self._folder_rename = loaded.enable_folder_rename if loaded is not None else False
        self._season_folders = loaded.enable_season_folders if loaded is not None else False
        self._locked = False
        self._listeners: list[PlanSettingListener] = []

    # ------------------------------------------------------------------ reads

    @property
    def mode(self) -> ScanMode:
        return self._mode

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def folder_rename(self) -> bool:
        return self._folder_rename

    @property
    def season_folders(self) -> bool:
        return self._season_folders

    def destination_root(self, mode: ScanMode) -> Path | None:
        """The Destination root set for ``mode``, as set (even while Folder rename is off)."""
        return self._destination_roots[mode]

    @property
    def locked(self) -> bool:
        """Whether a Plan is being built or applied, so no setting may change."""
        return self._locked

    def plan_options(self) -> PlanOptions:
        """The plan options for the current Mode, with the settings' rules applied.

        A Destination root is ignored while Folder rename is off; Season folder applies
        only in TV Mode and only while Folder rename is on.
        """
        root = self._destination_roots[self._mode] if self._folder_rename else None
        return PlanOptions(
            mode=self._mode,
            provider_id=self._provider_id,
            destination_root=root.expanduser().resolve() if root is not None else None,
            folder_rename=self._folder_rename,
            season_folders=(
                self._mode is ScanMode.TV and self._folder_rename and self._season_folders
            ),
        )

    # ----------------------------------------------------------------- writes

    def lock(self) -> None:
        """Refuse every change until :meth:`unlock` (a Plan is being built or applied)."""
        self._locked = True

    def unlock(self) -> None:
        self._locked = False

    def add_listener(self, listener: PlanSettingListener) -> None:
        """Call ``listener`` after each change to a setting a Plan is built with."""
        self._listeners.append(listener)

    def set_mode(self, mode: ScanMode) -> bool:
        """Set the Mode; return whether it changed."""
        return self._set("Mode", "_mode", mode)

    def set_provider(self, provider_id: str) -> bool:
        """Set the Provider (``tmdb``, ``tvdb`` or ``omdb``); return whether it changed."""
        return self._set("Provider", "_provider_id", provider_id)

    def set_destination_root(self, mode: ScanMode, root: Path | None) -> bool:
        """Set or clear the Destination root for ``mode``; return whether it changed."""
        self._refuse_while_locked()
        if self._destination_roots[mode] == root:
            return False
        self._destination_roots[mode] = root
        label = "TV" if mode is ScanMode.TV else "Film"
        self._changed(f"{label} Destination root")
        return True

    def set_folder_rename(self, value: bool) -> bool:
        """Turn Folder rename on or off; return whether it changed."""
        return self._set("Folder rename", "_folder_rename", value)

    def set_season_folders(self, value: bool) -> bool:
        """Turn Season folder on or off; return whether it changed."""
        return self._set("Season folder", "_season_folders", value)

    def _set(self, name: str, attribute: str, value: object) -> bool:
        self._refuse_while_locked()
        if getattr(self, attribute) == value:
            return False
        setattr(self, attribute, value)
        self._changed(name)
        return True

    def _refuse_while_locked(self) -> None:
        if self._locked:
            msg = (
                "Settings, Mode and Provider cannot change while a Plan is being built or applied."
            )
            raise SettingsLockedError(msg)

    def _changed(self, name: str) -> None:
        for listener in self._listeners:
            listener(name)
