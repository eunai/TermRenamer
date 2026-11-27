"""The session's settings owner: one place for the batch's settings, outside the screen.

It holds the values loaded at start with the session's changes on top, and yields
the plan options a Plan is built with. A change lasts for the session; the user
settings file is never written.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from termrenamer.app_bootstrap import Settings, ThemeName
from termrenamer.core.models import PROVIDER_IDS, PlanOptions, ScanMode
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.util.errors import ValidationError

PlanSettingListener = Callable[[str], None]
"""Called with a setting's name after a change to a setting a Plan is built with."""

ThemeListener = Callable[[ThemeName], None]
"""Called with the new Theme after the Theme changes."""


def locked_message(what: str) -> str:
    """The one wording of the lock's refusal, for ``what`` (such as "Mode")."""
    return f"{what} cannot change while a Plan is being built or applied."


class SettingsLockedError(ValidationError):
    """A setting was changed while a Plan is being built or applied."""


class SessionSettings:
    """The effective settings of this session.

    Mode, Provider, the two Destination roots, Folder rename, Season folder and Name
    taken are the settings a Plan is built with. A change to any of them is reported to
    the listeners, so that a Plan built with the old value can be discarded. The Theme
    changes no Plan; its own listeners are told. While locked (a Plan is being built
    or applied) every change is refused with :class:`SettingsLockedError`.

    ``keyed`` gives, per Mode, the ids of the Providers whose key is set (``None``
    treats every Provider as keyed). At start, and on every change of Mode, the
    Provider is the first of the Mode's Providers that has a key, or the first of
    them when none has.
    """

    def __init__(
        self,
        loaded: Settings | None = None,
        *,
        keyed: Mapping[ScanMode, frozenset[str]] | None = None,
    ) -> None:
        self._keyed = keyed
        self._mode = ScanMode.TV
        self._provider_id = self._first_keyed(ScanMode.TV)
        self._theme = loaded.theme if loaded is not None else ThemeName.DARK
        self._theme_listeners: list[ThemeListener] = []
        self._destination_roots: dict[ScanMode, Path | None] = {
            ScanMode.TV: loaded.tv_dest_folder if loaded is not None else None,
            ScanMode.FILM: loaded.film_dest_folder if loaded is not None else None,
        }
        self._folder_rename = loaded.enable_folder_rename if loaded is not None else False
        # Season folder cannot be on while Folder rename is off, even as loaded.
        self._season_folders = self._folder_rename and (
            loaded.enable_season_folders if loaded is not None else False
        )
        self._name_taken = loaded.name_taken if loaded is not None else NameTakenPolicy.SUFFIX
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

    @property
    def name_taken(self) -> NameTakenPolicy:
        return self._name_taken

    @property
    def theme(self) -> ThemeName:
        return self._theme

    def has_key(self, provider_id: str) -> bool:
        """Whether ``provider_id`` has its key set, for the current Mode."""
        if self._keyed is None:
            return True
        return provider_id in self._keyed.get(self._mode, frozenset())

    def _first_keyed(self, mode: ScanMode) -> str:
        offered = PROVIDER_IDS[mode]
        if self._keyed is None:
            return offered[0]
        keyed = self._keyed.get(mode, frozenset())
        return next((pid for pid in offered if pid in keyed), offered[0])

    def destination_root(self, mode: ScanMode) -> Path | None:
        """The Destination root set for ``mode``, as set (even while Folder rename is off)."""
        return self._destination_roots[mode]

    @property
    def locked(self) -> bool:
        """Whether a Plan is being built or applied, so no setting may change."""
        return self._locked

    def plan_options(self) -> PlanOptions:
        """The plan options for the current Mode, with the settings' rules applied.

        A Destination root is not used while Folder rename is off; Season folder applies
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
            name_taken=self._name_taken,
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

    def add_theme_listener(self, listener: ThemeListener) -> None:
        """Call ``listener`` after each change of the Theme."""
        self._theme_listeners.append(listener)

    def set_mode(self, mode: ScanMode) -> bool:
        """Set the Mode, and the Provider by the start rule; return whether the Mode changed."""
        if not self._set("Mode", "_mode", mode):
            return False
        self._set("Provider", "_provider_id", self._first_keyed(mode))
        return True

    def set_provider(self, provider_id: str) -> bool:
        """Set the Provider (``tmdb``, ``tvdb`` or ``omdb``); return whether it changed."""
        return self._set("Provider", "_provider_id", provider_id)

    def next_provider(self) -> bool:
        """Step to the Mode's next Provider, keyed or not; return whether it changed."""
        offered = PROVIDER_IDS[self._mode]
        current = offered.index(self._provider_id) if self._provider_id in offered else -1
        return self.set_provider(offered[(current + 1) % len(offered)])

    def set_theme(self, theme: ThemeName) -> bool:
        """Set the Theme; return whether it changed. No Plan is discarded."""
        self._refuse_while_locked()
        if self._theme is theme:
            return False
        self._theme = theme
        for listener in self._theme_listeners:
            listener(theme)
        return True

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
        """Turn Folder rename on or off; return whether it changed.

        Turning it off turns Season folder off too.
        """
        self._refuse_while_locked()
        if not value:
            self._season_folders = False
        return self._set("Folder rename", "_folder_rename", value)

    def set_season_folders(self, value: bool) -> bool:
        """Turn Season folder on or off; return whether it changed.

        It cannot be turned on while Folder rename is off.
        """
        self._refuse_while_locked()
        if value and not self._folder_rename:
            msg = "Season folder works only while Folder rename is on."
            raise ValidationError(msg)
        return self._set("Season folder", "_season_folders", value)

    def set_name_taken(self, policy: NameTakenPolicy) -> bool:
        """Set Name taken (add a number, or skip the file); return whether it changed."""
        return self._set("Name taken", "_name_taken", policy)

    def _set(self, name: str, attribute: str, value: object) -> bool:
        self._refuse_while_locked()
        if getattr(self, attribute) == value:
            return False
        setattr(self, attribute, value)
        self._changed(name)
        return True

    def _refuse_while_locked(self) -> None:
        if self._locked:
            raise SettingsLockedError(locked_message("Settings, Mode and Provider"))

    def _changed(self, name: str) -> None:
        for listener in self._listeners:
            listener(name)
