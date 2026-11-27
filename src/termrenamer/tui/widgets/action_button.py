"""A key's button: one flat line that shows its key and what it does.

It never takes focus, so every key reaches the app's key table. A click posts
:class:`ActionButton.Clicked`; whoever handles it presses the key the button shows.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.message import Message
from textual.widgets import Static


class ActionButton(Static, can_focus=False):
    """A one-line button labelled with its key and what it does, as `` b  Build the Plan ``.

    ``press_key`` is the Textual key name a click presses (such as ``enter``).
    """

    DEFAULT_CSS = """
    ActionButton {
        height: 1;
        width: auto;
        padding: 0 1;
        background: $tr-button;
        color: $accent;
    }
    ActionButton:hover {
        background: $tr-highlight;
    }
    ActionButton.-strong {
        background: $accent;
        color: $tr-on-accent;
        text-style: bold;
    }
    ActionButton.-plain {
        color: $foreground;
    }
    """

    class Clicked(Message):
        """The button was clicked."""

        def __init__(self, button: ActionButton) -> None:
            super().__init__()
            self.button = button

        @property
        def control(self) -> ActionButton:
            return self.button

    def __init__(self, key: str, label: str, *, press_key: str, **kwargs: Any) -> None:
        super().__init__(f"{key}  {label}", markup=False, **kwargs)
        self.press_key = press_key

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Clicked(self))
