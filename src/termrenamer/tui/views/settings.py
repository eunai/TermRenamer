"""Settings: one form with the two Destination roots, Folder rename, Season folder and Theme.

Every value is read from and written to the session's settings owner; a change lasts
until the app quits, and the User settings file is never written. Season folder
cannot be turned on while Folder rename is off.
"""

from __future__ import annotations

from pathlib import Path

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.markup import escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, Static, Switch

from termrenamer.app_bootstrap import ThemeName
from termrenamer.core.models import ScanMode
from termrenamer.session_settings import SessionSettings
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.util.errors import ValidationError

_ROOTS = {"tv-root": ScanMode.TV, "film-root": ScanMode.FILM}

VIEW_HINTS = (
    "[b $accent]↑↓[/] Move  [b $accent]enter[/] Edit or toggle  [b $accent]esc[/] Close"
    "  [b $accent]?[/] Help  [b $accent]q[/] Quit"
)


class ThemeChoice(Static, can_focus=True):
    """The Theme row's value: ``dark`` or ``light``; enter or space switches it."""

    BINDINGS = [
        Binding("enter", "switch", show=False),
        Binding("space", "switch", show=False),
    ]

    def __init__(self, value: ThemeName, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.value = value

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        parts = []
        for theme in ThemeName:
            if theme is self.value:
                parts.append(f"[b $tr-on-accent on $accent] {theme.value} [/]")
            else:
                parts.append(f"[$tr-dim on $tr-button] {theme.value} [/]")
        self.update(" ".join(parts))

    def action_switch(self) -> None:
        names = list(ThemeName)
        self.value = names[(names.index(self.value) + 1) % len(names)]
        self._draw()
        self.post_message(self.Switched())

    async def _on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        self.action_switch()

    class Switched(Message):
        """The person switched the Theme."""


class SettingsView(Screen[None]):
    """The Settings form, alone in the middle of the screen."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("up", "app.focus_previous", show=False),
        Binding("down", "app.focus_next", show=False),
    ]

    DEFAULT_CSS = """
    SettingsView {
        align-horizontal: center;
    }
    SettingsView #settings-form {
        width: 76;
        max-width: 100%;
        height: 1fr;
        padding: 2 2 0 2;
    }
    SettingsView #settings-title {
        text-style: bold;
    }
    SettingsView #settings-intro {
        color: $tr-dim;
        margin-bottom: 2;
    }
    SettingsView .setting-row {
        height: 1;
        margin-bottom: 1;
    }
    SettingsView .setting-label {
        width: 26;
    }
    SettingsView .setting-row:focus-within .setting-label {
        color: $accent;
    }
    SettingsView .setting-row.-off .setting-label {
        color: $tr-dim;
    }
    SettingsView Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
        background: $tr-field;
    }
    SettingsView Input:focus {
        border: none;
        text-style: underline;
    }
    SettingsView Switch {
        height: 1;
        width: auto;
        border: none;
        padding: 0;
        background: transparent;
    }
    SettingsView Switch:focus {
        border: none;
    }
    SettingsView Switch > .switch--slider {
        color: $accent;
        background: $tr-track;
    }
    SettingsView Switch:disabled > .switch--slider {
        color: $tr-track;
    }
    SettingsView .setting-value {
        width: auto;
        padding: 0 1;
        color: $tr-dim;
    }
    SettingsView .setting-value.-on {
        color: $success;
    }
    SettingsView #season-note {
        color: $tr-dim;
        padding: 0 0 0 2;
        margin: -1 0 1 0;
    }
    SettingsView ThemeChoice {
        width: auto;
    }
    SettingsView #settings-message {
        height: 1;
        margin-top: 1;
        color: $accent;
    }
    SettingsView #settings-close {
        margin-top: 1;
    }
    SettingsView #settings-hints {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    def __init__(self, owner: SessionSettings) -> None:
        super().__init__()
        self._owner = owner

    def compose(self) -> ComposeResult:
        owner = self._owner
        with Center(), Vertical(id="settings-form"):
            yield Static("Settings", id="settings-title")
            yield Static(
                "A change lasts until you quit. The User settings file is never written.",
                id="settings-intro",
            )
            for input_id, mode, label in (
                ("tv-root", ScanMode.TV, "TV Destination root"),
                ("film-root", ScanMode.FILM, "Film Destination root"),
            ):
                root = owner.destination_root(mode)
                with Horizontal(classes="setting-row"):
                    yield Static(f"  {label}", classes="setting-label")
                    yield Input(
                        value=str(root) if root is not None else "",
                        placeholder="not set",
                        id=input_id,
                    )
            with Horizontal(classes="setting-row", id="folder-rename-row"):
                yield Static("  Folder rename", classes="setting-label")
                yield Switch(owner.folder_rename, id="folder-rename")
                yield Static(classes="setting-value", id="folder-rename-value")
            with Horizontal(classes="setting-row", id="season-folder-row"):
                yield Static("  Season folder", classes="setting-label")
                yield Switch(owner.season_folders and owner.folder_rename, id="season-folder")
                yield Static(classes="setting-value", id="season-folder-value")
            yield Static("Season folder works only while Folder rename is on.", id="season-note")
            with Horizontal(classes="setting-row"):
                yield Static("  Theme", classes="setting-label")
                yield ThemeChoice(owner.theme, id="theme")
            yield Static("", id="settings-message")
            yield ActionButton(
                "esc", "Close", press_key="escape", id="settings-close", classes="-plain"
            )
        yield Static(VIEW_HINTS, id="settings-hints")

    def on_mount(self) -> None:
        self._show_switches()
        self.query_one("#tv-root", Input).focus()

    def on_descendant_focus(self) -> None:
        """Mark the row that has focus with ``▸``, as the mockup does."""
        for row in self.query(".setting-row"):
            label = row.query_one(".setting-label", Static)
            text = str(label.render().plain)[2:]  # type: ignore[union-attr]
            marker = "▸ " if row.has_focus_within else "  "
            label.update(f"{marker}{text}")

    def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        self.action_close()

    # ---------------------------------------------------------------- reading

    def _show_switches(self) -> None:
        folder_rename = self._owner.folder_rename
        season = self.query_one("#season-folder", Switch)
        season.disabled = not folder_rename
        self.query_one("#season-folder-row").set_class(not folder_rename, "-off")
        for switch_id, is_on in (
            ("folder-rename", folder_rename),
            ("season-folder", folder_rename and self._owner.season_folders),
        ):
            value = self.query_one(f"#{switch_id}-value", Static)
            if switch_id == "season-folder" and not folder_rename:
                value.update("unavailable")
                value.set_class(False, "-on")
            else:
                value.update("on" if is_on else "off")
                value.set_class(is_on, "-on")

    def _say(self, text: str) -> None:
        self.query_one("#settings-message", Static).update(escape(text))

    # ---------------------------------------------------------------- writing

    def _save_root(self, field: Input) -> None:
        mode = _ROOTS[field.id or ""]
        text = field.value.strip()
        root = Path(text).expanduser() if text else None
        label = "TV" if mode is ScanMode.TV else "Film"
        try:
            changed = self._owner.set_destination_root(mode, root)
        except ValidationError as exc:
            self._say(str(exc))
            return
        if changed:
            self._say(f"{label} Destination root {'set' if root else 'cleared'}.")

    @on(Input.Submitted)
    def _root_submitted(self, event: Input.Submitted) -> None:
        self._save_root(event.input)

    @on(Input.Blurred)
    def _root_left(self, event: Input.Blurred) -> None:
        self._save_root(event.input)

    @on(Switch.Changed, "#folder-rename")
    def _folder_rename_changed(self, event: Switch.Changed) -> None:
        try:
            self._owner.set_folder_rename(event.value)
            if not event.value:
                self._owner.set_season_folders(False)
                season = self.query_one("#season-folder", Switch)
                with season.prevent(Switch.Changed):
                    season.value = False
        except ValidationError as exc:
            self._say(str(exc))
        self._show_switches()

    @on(Switch.Changed, "#season-folder")
    def _season_folder_changed(self, event: Switch.Changed) -> None:
        try:
            self._owner.set_season_folders(event.value)
        except ValidationError as exc:
            self._say(str(exc))
        self._show_switches()

    @on(ThemeChoice.Switched)
    def _theme_switched(self) -> None:
        choice = self.query_one(ThemeChoice)
        try:
            self._owner.set_theme(choice.value)
        except ValidationError as exc:
            self._say(str(exc))
            return
        self._say(f"Theme: {choice.value.value}.")

    def action_close(self) -> None:
        for input_id in _ROOTS:
            self._save_root(self.query_one(f"#{input_id}", Input))
        self.dismiss()
