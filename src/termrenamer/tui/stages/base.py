"""What every Stage's view offers the app: its count, its footer lines and its key actions.

A view's ``action_<name>`` methods are the actions the key table runs at that Stage
(see :mod:`termrenamer.tui.keys`); the app looks on the current Stage's view first.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.content import Content
from textual.message import Message


class StageView(Vertical):
    """The body of the screen at one Stage."""

    DEFAULT_CSS = """
    StageView {
        height: 1fr;
    }
    """

    class Changed(Message):
        """The view's selection or content changed: the app draws the footer again."""

    def count_text(self) -> str:
        """The short count beside the Stages row, such as ``3 Sources``."""
        return ""

    def footer_lines(self) -> tuple[Content, ...]:
        """This Stage's footer lines, such as the selected Source's path."""
        return ()

    def key_enabled(self, action: str) -> bool:
        """Whether the footer shows the key that runs ``action`` here right now."""
        return True

    def redraw(self) -> None:
        """Draw again what depends on the theme's colours."""

    def changed(self) -> None:
        self.post_message(self.Changed())
