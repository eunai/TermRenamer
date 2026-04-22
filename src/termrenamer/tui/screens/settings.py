"""Full-screen Settings: destination + layout tabs (live app).

The live TUI exposes **four** Settings tabs (in order): TV, Film, Layout, and a
generic Placeholder tab reserved for future options.

- TV / Film: destination folder inputs + a ``[+ folder]`` picker button.
- Layout: folder rename + season-folder toggles (season disabled unless folder
  rename is on).
- Placeholder: intentionally minimal.

Destination and layout saves write session overrides to
``TermRenamerApp._settings_overrides`` and, when the app was constructed with a
bootstrap :class:`termrenamer.app_bootstrap.Settings` object, replace that
snapshot via :func:`dataclasses.replace` so new values flow into planning without
mutating a frozen instance in place.

Never rewrites ``.env`` on disk; never creates or reads ``mock_settings.toml``
(that file is mock-only under ``dev_textual/``).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)
from textual_fspicker import SelectDirectory

from termrenamer.tui.screens.footer_bindings import footer_bindings_for_modal


class SettingsScreen(Screen[None]):
    """Settings screen: TV / Film / Layout tabs, plus an extra Placeholder tab."""

    BINDINGS = footer_bindings_for_modal(screen_kind="settings")

    DEFAULT_CSS = """
    SettingsScreen #settings-panel {
        height: 1fr;
        border: round $accent;
        background: $surface;
        border-title-align: left;
        border-title-color: $accent;
        padding: 1 2;
    }
    SettingsScreen #settings-tabs {
        height: 1fr;
        border: none;
    }
    SettingsScreen .settings-tab-inner {
        padding: 1 0;
        height: auto;
    }
    SettingsScreen .settings-section-header {
        text-style: bold;
        margin: 0 0 1 0;
    }
    SettingsScreen .settings-destination-row {
        height: auto;
        align-vertical: middle;
    }
    SettingsScreen .settings-destination-row Input {
        width: 1fr;
        margin: 0 1 0 0;
    }
    SettingsScreen .settings-destination-row Button {
        min-width: 12;
    }
    SettingsScreen .settings-layout-checkboxes {
        height: auto;
    }
    SettingsScreen .settings-layout-checkboxes Checkbox {
        margin: 0 0 1 0;
    }
    SettingsScreen #settings-save-toast {
        dock: bottom;
        height: 1;
        width: auto;
        padding: 0 1;
        color: $success;
        text-style: italic;
        content-align: left middle;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._toast_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="settings-panel"):
            with TabbedContent(id="settings-tabs"):
                with TabPane("TV", id="tab-settings-tv"), Vertical(classes="settings-tab-inner"):
                    yield Static("Destination", classes="settings-section-header")
                    with Horizontal(classes="settings-destination-row"):
                        yield Input(
                            placeholder="Destination folder path",
                            id="tv-destination-input",
                        )
                        yield Button(
                            "[+ folder]",
                            id="tv-destination-pick",
                            variant="primary",
                        )
                with (
                    TabPane("Film", id="tab-settings-film"),
                    Vertical(classes="settings-tab-inner"),
                ):
                    yield Static("Destination", classes="settings-section-header")
                    with Horizontal(classes="settings-destination-row"):
                        yield Input(
                            placeholder="Destination folder path",
                            id="film-destination-input",
                        )
                        yield Button(
                            "[+ folder]",
                            id="film-destination-pick",
                            variant="primary",
                        )
                with (
                    TabPane("Layout", id="tab-settings-layout"),
                    Vertical(classes="settings-tab-inner"),
                ):
                    yield Static("Rename layout", classes="settings-section-header")
                    with Vertical(classes="settings-layout-checkboxes"):
                        yield Checkbox(
                            "Enable folder rename",
                            id="enable-folder-rename",
                        )
                        yield Checkbox(
                            "Enable season folders (TV)",
                            id="enable-season-folders",
                        )
                with TabPane("Placeholder", id="tab-settings-extra"):
                    yield Static("Placeholder (more settings to come)")
            yield Static("", id="settings-save-toast")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#settings-panel", Vertical).border_title = " settings "
        tv_initial = self._load_destination("tv")
        film_initial = self._load_destination("film")
        self.query_one("#tv-destination-input", Input).value = tv_initial
        self.query_one("#film-destination-input", Input).value = film_initial
        folder_rename = self._load_folder_rename()
        season_folders = self._load_season_folders() if folder_rename else False
        fr_box = self.query_one("#enable-folder-rename", Checkbox)
        fr_box.value = folder_rename
        sf_box = self.query_one("#enable-season-folders", Checkbox)
        sf_box.value = season_folders
        sf_box.disabled = not folder_rename
        toast = self.query_one("#settings-save-toast", Static)
        toast.display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "tv-destination-pick":
            self._open_destination_picker("tv-destination-input", "tv")
        elif bid == "film-destination-pick":
            self._open_destination_picker("film-destination-input", "film")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        iid = event.input.id
        if iid == "tv-destination-input":
            self._persist("tv", event.value)
        elif iid == "film-destination-input":
            self._persist("film", event.value)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "enable-folder-rename":
            if not event.value:
                sf = self.query_one("#enable-season-folders", Checkbox)
                sf.value = False
                sf.disabled = True
            else:
                self.query_one("#enable-season-folders", Checkbox).disabled = False
            self._persist_layout(
                event.value,
                self.query_one("#enable-season-folders", Checkbox).value if event.value else False,
            )
        elif event.checkbox.id == "enable-season-folders":
            self._persist_layout(
                self.query_one("#enable-folder-rename", Checkbox).value,
                event.value,
            )

    def _open_destination_picker(self, input_id: str, kind: Literal["tv", "film"]) -> None:
        def _cb(path: Path | None) -> None:
            if path is None:
                return
            self.query_one(f"#{input_id}", Input).value = str(path)
            self._persist(kind, str(path))

        self.app.push_screen(SelectDirectory(str(Path.cwd())), _cb)

    def _load_destination(self, kind: Literal["tv", "film"]) -> str:
        """Session override wins; otherwise fall back to the production ``Settings``."""
        app = self.app
        overrides = getattr(app, "_settings_overrides", None)
        if isinstance(overrides, dict):
            override = overrides.get(kind)
            if override is not None and isinstance(override, Path):
                return str(override)
        settings = getattr(app, "_settings", None)
        if settings is not None:
            attr = "tv_dest_folder" if kind == "tv" else "film_dest_folder"
            value = getattr(settings, attr, None)
            if value is not None:
                return str(value)
        return ""

    def _load_folder_rename(self) -> bool:
        app = self.app
        overrides = getattr(app, "_settings_overrides", None)
        if isinstance(overrides, dict):
            o = overrides.get("folder_rename")
            if isinstance(o, bool):
                return o
        settings = getattr(app, "_settings", None)
        if settings is not None:
            return bool(settings.enable_folder_rename)
        return False

    def _load_season_folders(self) -> bool:
        app = self.app
        overrides = getattr(app, "_settings_overrides", None)
        if isinstance(overrides, dict):
            o = overrides.get("season_folders")
            if isinstance(o, bool):
                return o
        settings = getattr(app, "_settings", None)
        if settings is not None:
            return bool(settings.enable_season_folders)
        return False

    def _persist_layout(self, folder_rename: bool, season_folders: bool) -> None:
        """Session overrides + ``Settings`` snapshot for layout toggles."""
        if not folder_rename:
            season_folders = False
        app = self.app
        overrides = getattr(app, "_settings_overrides", None)
        if not isinstance(overrides, dict):
            overrides = {}
            app._settings_overrides = overrides  # type: ignore[attr-defined]
        overrides["folder_rename"] = folder_rename
        overrides["season_folders"] = season_folders
        settings = getattr(app, "_settings", None)
        if settings is not None:
            app._settings = replace(  # type: ignore[attr-defined]
                settings,
                enable_folder_rename=folder_rename,
                enable_season_folders=season_folders,
            )
        log = getattr(app, "_log_line", None)
        if callable(log):
            log(
                "[dim]Saved layout: folder rename = "
                f"{folder_rename!r}, season folders = {season_folders!r}[/dim]",
            )
        self._show_save_toast("Layout settings saved")

    def _persist(self, kind: Literal["tv", "film"], value: str) -> None:
        """Write session overrides and snapshot ``Settings`` when the app has one."""
        app = self.app
        overrides = getattr(app, "_settings_overrides", None)
        if not isinstance(overrides, dict):
            overrides = {}
            app._settings_overrides = overrides  # type: ignore[attr-defined]
        trimmed = value.strip()
        path_obj = Path(trimmed).expanduser() if trimmed else None
        overrides[kind] = path_obj
        settings = getattr(app, "_settings", None)
        if settings is not None:
            if kind == "tv":
                app._settings = replace(settings, tv_dest_folder=path_obj)  # type: ignore[attr-defined]
            else:
                app._settings = replace(settings, film_dest_folder=path_obj)  # type: ignore[attr-defined]
        label = "TV" if kind == "tv" else "Film"
        log = getattr(app, "_log_line", None)
        if callable(log):
            if trimmed:
                log(f"[dim]Saved {label} destination → {trimmed}[/dim]")
            else:
                log(f"[dim]Cleared {label} destination override[/dim]")
        self._show_save_toast(f"{label} destination saved")

    def _show_save_toast(self, message: str) -> None:
        toast = self.query_one("#settings-save-toast", Static)
        toast.update(message)
        toast.display = True
        toast.styles.opacity = 1.0
        if self._toast_timer is not None:
            self._toast_timer.stop()
        toast.styles.animate("opacity", value=0.0, duration=0.6, delay=2.4)
        self._toast_timer = self.set_timer(3.0, self._hide_save_toast)

    def _hide_save_toast(self) -> None:
        toast = self.query_one("#settings-save-toast", Static)
        toast.display = False
        toast.styles.opacity = 1.0
        self._toast_timer = None

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_noop(self) -> None:
        """Shadow app bindings while this screen is on top (Footer uses ``show=False``)."""

    def action_open_settings_proxy(self) -> None:
        """No-op when already on Settings; kept for symmetry with Help."""
        app = self.app
        action = getattr(app, "action_open_settings", None)
        if callable(action):
            action()

    def action_open_help_proxy(self) -> None:
        app = self.app
        action = getattr(app, "action_open_help", None)
        if callable(action):
            action()

    async def action_quit(self) -> None:
        await self.app.action_quit()
