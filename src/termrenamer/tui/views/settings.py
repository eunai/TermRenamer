"""Settings: one form with the Destination roots, Folder rename, Season folder, Name taken,
Show posters and Theme.

Every value is read from and written to the session's settings owner; a change lasts
until the app quits, and the User settings file is never written. Season folder
cannot be turned on while Folder rename is off. When Posters are unavailable, Show
posters shows as unavailable with the reason; when the screen is too small for them, it
says the size they need.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.content import Content
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, Static, Switch

from termrenamer.app_bootstrap import ThemeName
from termrenamer.core.models import ScanMode
from termrenamer.core.policies import NameTakenPolicy
from termrenamer.session_settings import SessionSettings
from termrenamer.tui.keys import VIEW_HINTS
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.footer import hints_markup
from termrenamer.tui.words import NO_NUL, NUL, folder_text, mode_label, path_shown
from termrenamer.util.errors import ValidationError

_ROOTS = {"tv-root": ScanMode.TV, "film-root": ScanMode.FILM}


class Choice(Static, can_focus=True):
    """A row's value picked from a few words, such as ``dark`` or ``light``.

    ``enter`` or space steps to the next word; the row then posts :class:`Choice.Switched`.
    """

    BINDINGS = [
        Binding("enter", "switch", show=False),
        Binding("space", "switch", show=False),
    ]

    def __init__(self, value: StrEnum, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.value = value

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        parts = []
        for word in type(self.value):
            if word is self.value:
                parts.append(f"[b $tr-on-accent on $accent] {word.value} [/]")
            else:
                parts.append(f"[$tr-dim on $tr-button] {word.value} [/]")
        self.update(" ".join(parts))

    def action_switch(self) -> None:
        words = list(type(self.value))
        self.value = words[(words.index(self.value) + 1) % len(words)]
        self._draw()
        self.post_message(self.Switched(self))

    async def _on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        self.action_switch()

    class Switched(Message):
        """The person switched the row's value."""

        def __init__(self, choice: Choice) -> None:
            super().__init__()
            self.choice = choice

        @property
        def control(self) -> Choice:
            return self.choice


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
    SettingsView .setting-note {
        color: $tr-dim;
        padding: 0 0 0 2;
        margin: -1 0 1 0;
    }
    SettingsView Choice {
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

    def __init__(
        self,
        owner: SessionSettings,
        posters_unavailable: str | None = None,
        *,
        posters_need: str | None = None,
    ) -> None:
        """``posters_unavailable`` is why Posters cannot be shown, or ``None`` when they can;
        ``posters_need`` is the screen size they need when the screen is smaller, such as
        "at least 100 columns by 35 rows"."""
        super().__init__()
        self._owner = owner
        self._posters_unavailable = posters_unavailable
        self._posters_need = posters_need

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
                yield Switch(owner.season_folders, id="season-folder")
                yield Static(classes="setting-value", id="season-folder-value")
            yield Static(
                "Season folder works only while Folder rename is on.",
                id="season-note",
                classes="setting-note",
            )
            with Horizontal(classes="setting-row"):
                yield Static("  Name taken", classes="setting-label")
                yield Choice(owner.name_taken, id="name-taken")
            yield Static(
                "suffix adds a number such as (1); skip leaves the file where it is.",
                id="name-taken-note",
                classes="setting-note",
            )
            with Horizontal(classes="setting-row", id="show-posters-row"):
                yield Static("  Show posters", classes="setting-label")
                yield Switch(owner.show_posters, id="show-posters")
                yield Static(classes="setting-value", id="show-posters-value")
            if self._posters_unavailable is not None:
                yield Static(
                    Content(f"Unavailable: {self._posters_unavailable}."),
                    id="show-posters-note",
                    classes="setting-note",
                )
            elif self._posters_need is not None:
                yield Static(
                    Content(f"Posters show when the screen is {self._posters_need}."),
                    id="show-posters-note",
                    classes="setting-note",
                )
            with Horizontal(classes="setting-row"):
                yield Static("  Theme", classes="setting-label")
                yield Choice(owner.theme, id="theme")
            yield Static("", id="settings-message")
            yield ActionButton(
                "esc", "Close", press_key="escape", id="settings-close", classes="-plain"
            )
        yield Static(hints_markup(VIEW_HINTS["settings"]), id="settings-hints")

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

    def show_values(self) -> None:
        """Show the owner's values again, after a change made outside the form (``i``)."""
        self._show_switches()

    def _show_switches(self) -> None:
        """Show the owner's values: the switches, their words and Season folder's rule."""
        folder_rename = self._owner.folder_rename
        for switch_id, on_value in (
            ("folder-rename", folder_rename),
            ("season-folder", self._owner.season_folders),
            ("show-posters", self._owner.show_posters),
        ):
            switch = self.query_one(f"#{switch_id}", Switch)
            with switch.prevent(Switch.Changed):
                switch.value = on_value
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
        unavailable = self._posters_unavailable is not None
        self.query_one("#show-posters", Switch).disabled = unavailable
        self.query_one("#show-posters-row").set_class(unavailable, "-off")
        posters = self.query_one("#show-posters-value", Static)
        if unavailable:
            posters.update("unavailable")
            posters.set_class(False, "-on")
        else:
            posters.update("on" if self._owner.show_posters else "off")
            posters.set_class(self._owner.show_posters, "-on")

    def _say(self, text: str) -> None:
        self.query_one("#settings-message", Static).update(Content(text))

    # ---------------------------------------------------------------- writing

    def _save_root(self, field: Input) -> None:
        """Set the Destination root typed in ``field``. A path that cannot be used, such
        as ``~someone/TV`` for a user the system does not know or one holding a NUL
        character, is refused with a message, and the root set before is kept."""
        mode = _ROOTS[field.id or ""]
        text = field.value.strip()
        label = mode_label(mode)
        if NUL in text:
            self._refuse_root(mode, text, NO_NUL)
            return
        try:
            root = Path(text).expanduser() if text else None
        except (RuntimeError, OSError) as exc:
            self._refuse_root(mode, text, str(exc))
            return
        try:
            changed = self._owner.set_destination_root(mode, root)
        except ValidationError as exc:
            self._say(str(exc))
            return
        if changed:
            self._say(f"{label} Destination root {'set' if root else 'cleared'}.")

    def _refuse_root(self, mode: ScanMode, text: str, reason: str) -> None:
        """Say the root typed as ``text`` cannot be used and which root is kept."""
        kept = self._owner.destination_root(mode)
        still = folder_text(kept) if kept is not None else "not set"
        self._say(
            f"The {mode_label(mode)} Destination root {path_shown(text)} cannot be used "
            f"({reason}); it is still {still}."
        )

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

    @on(Switch.Changed, "#show-posters")
    def _show_posters_changed(self, event: Switch.Changed) -> None:
        self._owner.set_show_posters(event.value)
        self._show_switches()
        self._say(f"Show posters: {'on' if event.value else 'off'}.")

    @on(Choice.Switched, "#name-taken")
    def _name_taken_switched(self, event: Choice.Switched) -> None:
        value = event.choice.value
        assert isinstance(value, NameTakenPolicy)
        self._switch(event.choice, "Name taken", lambda: self._owner.set_name_taken(value))

    @on(Choice.Switched, "#theme")
    def _theme_switched(self, event: Choice.Switched) -> None:
        value = event.choice.value
        assert isinstance(value, ThemeName)
        self._switch(event.choice, "Theme", lambda: self._owner.set_theme(value))

    def _switch(self, choice: Choice, label: str, change: Callable[[], object]) -> None:
        try:
            change()
        except ValidationError as exc:
            self._say(str(exc))
            return
        self._say(f"{label}: {choice.value.value}.")

    def action_close(self) -> None:
        for input_id in _ROOTS:
            self._save_root(self.query_one(f"#{input_id}", Input))
        self.dismiss()
