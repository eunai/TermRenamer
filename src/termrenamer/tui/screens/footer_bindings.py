"""Shared Footer bindings for full-screen modals (Help / Settings).

Both screens share the same contract:

* The screen's dismiss key is relabeled for its kind (``close settings`` /
  ``close help``), so the Footer reads naturally.
* The companion screen's open shortcut (Help from Settings, Settings from
  Help) is exposed as a visible Footer action, so users can jump between
  the two without returning to the main view first.
* ``q`` and ``Escape`` always dismiss the screen, but are hidden from the
  Footer to keep it uncluttered.
* The main-app bindings that would otherwise fire underneath (``m``, ``p``,
  ``b``, ``a``, ``ctrl+f``) are shadowed by ``noop`` so modal-context
  keystrokes never leak into the hidden app beneath.
* ``ctrl+q`` is re-proxied to :meth:`App.action_quit` so the global quit
  still works from inside the modal.

Mirrors ``dev_textual/tui_mock/screens/footer_bindings.py``.
"""

from __future__ import annotations

from typing import Literal

from textual.binding import Binding, BindingType


def footer_bindings_for_modal(*, screen_kind: Literal["settings", "help"]) -> list[BindingType]:
    """Return the shared Footer bindings for ``screen_kind``.

    Args:
        screen_kind: ``"settings"`` or ``"help"`` — drives which shortcut
            appears in the Footer as the dismiss key vs the companion-open key.

    Returns:
        Ordered list of bindings; the first two are visible in the Footer,
        the remainder are active but hidden.
    """
    if screen_kind == "settings":
        dismiss_key = Binding("ctrl+comma", "close", "close settings")
        other_key = Binding("f1", "open_help_proxy", "open help")
    else:
        dismiss_key = Binding("f1", "close", "close help")
        other_key = Binding("ctrl+comma", "open_settings_proxy", "open settings")
    return [
        dismiss_key,
        other_key,
        Binding("q", "close", "", show=False),
        Binding("escape", "close", "", show=False),
        Binding("m", "noop", "", show=False),
        Binding("p", "noop", "", show=False),
        Binding("b", "noop", "", show=False),
        Binding("a", "noop", "", show=False),
        Binding("ctrl+f", "noop", "", show=False),
        Binding("ctrl+q", "quit", "", show=False),
    ]
