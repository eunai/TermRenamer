"""The full-screen views over the Stages, one module each: Settings, Logs and Help."""

from termrenamer.tui.views.help import HelpView
from termrenamer.tui.views.logs import LogsView
from termrenamer.tui.views.settings import SettingsView

__all__ = ["HelpView", "LogsView", "SettingsView"]
