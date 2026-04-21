"""Ctrl+F quick-pick: choose folder vs file before opening the fspicker modal.

Mirrors ``dev_textual/tui_mock/screens/add_source.py``. Returned values match
the mock's contract so the host app's callback stays identical:

* ``"folder"`` → open the directory picker.
* ``"file"`` → open the file picker.
* ``None`` → user cancelled (``q`` / ``Escape``).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static


class AddSourceQuickPick(ModalScreen[str | None]):
    """Small modal that routes :kbd:`Ctrl+F` to folder- vs file-picker."""

    BINDINGS = [
        ("1", "pick_folder", "1 folder"),
        ("2", "pick_file", "2 file"),
        ("escape", "cancel", "esc cancel"),
        ("q", "cancel", "q cancel"),
        ("enter", "activate_choice", "enter select"),
    ]

    DEFAULT_CSS = """
    AddSourceQuickPick #add-source-dialog {
        align: center middle;
    }
    AddSourceQuickPick #add-source-panel {
        width: 44;
        height: auto;
        border: round $accent;
        background: $surface;
        border-title-align: left;
        border-title-color: $accent;
        padding: 1 2;
    }
    AddSourceQuickPick #add-source-buttons {
        height: auto;
        margin-top: 1;
    }
    AddSourceQuickPick #add-source-buttons Button {
        margin: 0 1 0 0;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="add-source-dialog"):  # noqa: SIM117
            with Vertical(id="add-source-panel"):
                yield Static(
                    "Pick folder or file. Tab switches focus; Enter confirms.",
                    id="add-source-hint",
                )
                with Horizontal(id="add-source-buttons"):
                    yield Button("[1] folder", id="pick-folder", variant="primary")
                    yield Button("[2] file", id="pick-file", variant="primary")
                yield Footer()

    def on_mount(self) -> None:
        panel = self.query_one("#add-source-panel", Vertical)
        panel.border_title = " add source "

    def action_pick_folder(self) -> None:
        self.dismiss("folder")

    def action_pick_file(self) -> None:
        self.dismiss("file")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_activate_choice(self) -> None:
        """Forward ``Enter`` to whichever Button currently has focus."""
        focused = self.focused
        if isinstance(focused, Button):
            focused.press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pick-folder":
            self.dismiss("folder")
        elif event.button.id == "pick-file":
            self.dismiss("file")
