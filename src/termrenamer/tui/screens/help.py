"""Full-screen Help: keyboard shortcuts reference.

Mirrors ``dev_textual/tui_mock/screens/help.py``. The body is rendered from
a module-level constant so it can be snapshotted by tests without having to
spin up the Textual runtime.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from termrenamer.tui.screens.footer_bindings import footer_bindings_for_modal

HELP_BODY = """
[b]Keyboard shortcuts[/b]

  [b]m[/b]          Toggle mode (TV / Film)
  [b]p[/b]          Cycle provider for the current mode
  [b]a[/b]          Toggle bottom tab (Activity / Logs)
  [b]b[/b]          Build plan
  [b]ctrl+q[/b]     Quit app
  [b]q[/b]          Close top modal/screen (Help, Settings, add-source picker)
  [b]ctrl+f[/b]     Open add-source quick-pick (folder / file)
  [b]f1[/b]         Open this Help screen
  [b]ctrl+,[/b]     Open Settings screen (same as the settings button; Ctrl+,)
"""


class HelpScreen(Screen[None]):
    """Help reference; :kbd:`q`, :kbd:`Esc`, or :kbd:`F1` returns to the main UI."""

    BINDINGS = footer_bindings_for_modal(screen_kind="help")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="help-panel"):
            yield Static(HELP_BODY.strip(), id="help-body")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#help-panel", Vertical).border_title = " help "

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_noop(self) -> None:
        """Shadow app bindings while this screen is on top (Footer uses ``show=False``)."""

    def action_open_settings_proxy(self) -> None:
        """Forward ``ctrl+comma`` from Help → main app's Settings action."""
        app = self.app
        action = getattr(app, "action_open_settings", None)
        if callable(action):
            action()

    def action_open_help_proxy(self) -> None:
        """No-op when already on Help; kept for symmetry with Settings."""
        app = self.app
        action = getattr(app, "action_open_help", None)
        if callable(action):
            action()

    async def action_quit(self) -> None:
        await self.app.action_quit()
