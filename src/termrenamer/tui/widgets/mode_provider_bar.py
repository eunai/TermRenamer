"""Top bar: scan mode (TV / Film) and metadata provider toggle switches.

Dolphie-style ``Switch`` toggles replace the previous ``Select`` dropdowns:
TV vs Film is a single two-position ``Switch`` (left/off = TV, right/on = Film);
provider selection remains mutually-exclusive ``Switch``es, and providers that do
not apply to the current mode are **hidden** (``display = False`` on the switch
and its peer ``Label``) so invalid combinations cannot be chosen (FR-002 /
FR-003). An inline ``settings`` button posts :class:`OpenSettingsRequested` so
the host app can surface the modal without a dedicated binding.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Label, Static, Switch

from termrenamer.core.models import ScanMode


class ScanModeChanged(Message):
    """User selected TV vs Film."""

    def __init__(self, mode: ScanMode) -> None:
        self.mode = mode
        super().__init__()


class ProviderChanged(Message):
    """User selected provider id: ``tmdb``, ``tvdb``, or ``omdb``."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__()


class OpenSettingsRequested(Message):
    """User clicked the settings control in the mode/provider bar."""

    def __init__(self) -> None:
        super().__init__()


_MODE_TOGGLE_ID = "mode-toggle"

_PROVIDER_SWITCH_IDS: tuple[str, ...] = ("provider-tmdb", "provider-tvdb", "provider-omdb")

_PROVIDER_LABEL_IDS: dict[str, str] = {
    "provider-tmdb": "provider-tmdb-label",
    "provider-tvdb": "provider-tvdb-label",
    "provider-omdb": "provider-omdb-label",
}

_ALLOWED_PROVIDERS: dict[ScanMode, frozenset[str]] = {
    ScanMode.TV: frozenset({"provider-tmdb", "provider-tvdb"}),
    ScanMode.FILM: frozenset({"provider-tmdb", "provider-omdb"}),
}


def _provider_id_from_switch_id(switch_id: str) -> str:
    """``provider-tmdb`` -> ``tmdb`` (matches the old `Select` values)."""
    return switch_id.removeprefix("provider-")


class ModeProviderBar(Horizontal):
    """Mode and provider toggle switches (FR-002 / FR-003).

    Internally the widget guards against re-entrant watcher calls while it
    flips peer switches so that a single user click produces **exactly one**
    ``ScanModeChanged`` or ``ProviderChanged`` message.
    """

    DEFAULT_CSS = """
    ModeProviderBar {
        height: 2;
        width: 100%;
        padding: 0 1;
        background: $boost;
        align-vertical: top;
    }
    /* Reserved bottom border row: same footprint blurred vs focused (no jitter). */
    ModeProviderBar Switch {
        background: transparent;
        border: none;
        border-bottom: hkey $boost;
        margin: 0;
        padding: 0;
    }
    ModeProviderBar Switch:focus {
        border: none;
        border-bottom: hkey $accent;
    }
    /* Provider switches fall through to Textual's stock $success (.-on) / off-state. */
    /* TV (off) and Film (on) both paint the slider in $success to match Textual's */
    /* stock "on" color across all built-in themes (including :light variants). */
    ModeProviderBar #mode-toggle > .switch--slider,
    ModeProviderBar #mode-toggle.-on > .switch--slider {
        color: $success;
    }
    ModeProviderBar Switch:disabled {
        opacity: 40%;
    }
    ModeProviderBar Label {
        padding: 0 1 0 0;
        color: $text-muted;
    }
    ModeProviderBar Label.-active {
        color: $text;
        text-style: bold;
    }
    /* One cell only — unconstrained Static grows to fill Horizontal free space. */
    ModeProviderBar .mpb-sep {
        width: 1;
        min-width: 1;
        color: $text-muted;
        padding: 0 2;
    }
    /* Flex spacer pushes the settings button to the far right. */
    ModeProviderBar .mpb-spacer {
        width: 1fr;
        min-width: 1;
        height: 1;
    }
    ModeProviderBar #open-settings {
        margin: 0;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Mode:")
        yield Label("TV", id="mode-tv-label", classes="-active")
        yield Switch(value=False, id=_MODE_TOGGLE_ID)
        yield Label("Film", id="mode-film-label")
        yield Static("│", classes="mpb-sep")
        yield Label("Provider:")
        yield Switch(value=True, id="provider-tmdb")
        yield Label("TMDB", id="provider-tmdb-label", classes="-active")
        yield Switch(value=False, id="provider-tvdb")
        yield Label("TheTVDB", id="provider-tvdb-label")
        yield Switch(value=False, id="provider-omdb")
        yield Label("OMDb", id="provider-omdb-label")
        yield Static("", classes="mpb-spacer")
        yield Button("settings", id="open-settings", variant="default")

    def on_mount(self) -> None:
        self._apply_provider_mask(ScanMode.TV, emit=False)
        self._emit_initial()

    def toggle_mode(self) -> None:
        """Flip TV ↔ Film (used by global ``m`` binding)."""
        sw = self.query_one(f"#{_MODE_TOGGLE_ID}", Switch)
        sw.value = not bool(sw.value)

    def cycle_provider(self) -> None:
        """Advance to the next allowed provider for the current mode.

        Order is the fixed declaration order in ``_PROVIDER_SWITCH_IDS`` filtered
        by ``_ALLOWED_PROVIDERS`` (TV: tmdb→tvdb; Film: tmdb→omdb). Setting the
        target switch to ``True`` replays the same handler path as a user click,
        emitting exactly one ``ProviderChanged``.
        """
        mode = ScanMode.FILM if self._switch_value(_MODE_TOGGLE_ID) else ScanMode.TV
        allowed = _ALLOWED_PROVIDERS[mode]
        ordered = tuple(pid for pid in _PROVIDER_SWITCH_IDS if pid in allowed)
        if len(ordered) <= 1:
            return
        current = next((pid for pid in _PROVIDER_SWITCH_IDS if self._switch_value(pid)), None)
        next_sid = (
            ordered[0]
            if current not in ordered
            else ordered[(ordered.index(current) + 1) % len(ordered)]
        )
        if next_sid == current:
            return
        self.query_one(f"#{next_sid}", Switch).value = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Forward the settings button click to the host app."""
        if event.button.id == "open-settings":
            self.post_message(OpenSettingsRequested())

    # ---------------------------------------------------------------- events

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle user toggles; programmatic flips are suppressed via ``prevent``."""
        sid = event.switch.id
        if sid is None:
            return

        if sid == _MODE_TOGGLE_ID:
            self._handle_mode_change(turned_on=event.value)
        elif sid in _PROVIDER_SWITCH_IDS:
            self._handle_provider_change(sid, turned_on=event.value)

    # --------------------------------------------------------------- helpers

    def _emit_initial(self) -> None:
        self.post_message(ScanModeChanged(ScanMode.TV))
        self.post_message(ProviderChanged("tmdb"))

    def _handle_mode_change(self, *, turned_on: bool) -> None:
        new_mode = ScanMode.FILM if turned_on else ScanMode.TV
        self._set_mode_label_active(new_mode)
        self._apply_provider_mask(new_mode, emit=True)
        self.post_message(ScanModeChanged(new_mode))

    def _handle_provider_change(self, switch_id: str, *, turned_on: bool) -> None:
        if not turned_on:
            # Exactly one provider must stay ON among those visible for this mode.
            mode = ScanMode.FILM if self._switch_value(_MODE_TOGGLE_ID) else ScanMode.TV
            allowed = _ALLOWED_PROVIDERS[mode]
            if not any(self._switch_value(pid) for pid in _PROVIDER_SWITCH_IDS if pid in allowed):
                self._set_switch(switch_id, True)
            return

        for pid in _PROVIDER_SWITCH_IDS:
            if pid != switch_id:
                self._set_switch(pid, False)
        self._set_provider_label_active(switch_id)
        self.post_message(ProviderChanged(_provider_id_from_switch_id(switch_id)))

    def _apply_provider_mask(self, mode: ScanMode, *, emit: bool) -> None:
        """Hide providers that do not apply to ``mode``; fall back to TMDB.

        Out-of-mode providers are fully hidden (``display = False`` on both the
        switch and its label) rather than disabled, so invalid combinations are
        not merely greyed out — they literally do not occupy a cell. TMDB is
        kept as the "always on" fallback when the previously active provider is
        hidden by the mask.
        """
        allowed = _ALLOWED_PROVIDERS[mode]
        for pid in _PROVIDER_SWITCH_IDS:
            switch = self.query_one(f"#{pid}", Switch)
            label = self.query_one(f"#{_PROVIDER_LABEL_IDS[pid]}", Label)
            if pid not in allowed:
                self._set_switch(pid, False)
                switch.display = False
                label.display = False
                switch.disabled = False
            else:
                switch.display = True
                label.display = True
                switch.disabled = False

        current_on = next(
            (pid for pid in _PROVIDER_SWITCH_IDS if self._switch_value(pid)),
            None,
        )
        if current_on is None or current_on not in allowed:
            if current_on is not None:
                self._set_switch(current_on, False)
            self._set_switch("provider-tmdb", True)
            self._set_provider_label_active("provider-tmdb")
            if emit:
                self.post_message(ProviderChanged("tmdb"))

    def _set_switch(self, switch_id: str, value: bool) -> None:
        switch = self.query_one(f"#{switch_id}", Switch)
        if switch.value == value:
            return
        with self.prevent(Switch.Changed):
            switch.value = value

    def _switch_value(self, switch_id: str) -> bool:
        return bool(self.query_one(f"#{switch_id}", Switch).value)

    def _set_mode_label_active(self, mode: ScanMode) -> None:
        tv_label = self.query_one("#mode-tv-label", Label)
        film_label = self.query_one("#mode-film-label", Label)
        tv_label.set_class(mode is ScanMode.TV, "-active")
        film_label.set_class(mode is ScanMode.FILM, "-active")

    def _set_provider_label_active(self, active_switch_id: str) -> None:
        for pid, lid in _PROVIDER_LABEL_IDS.items():
            label = self.query_one(f"#{lid}", Label)
            label.set_class(pid == active_switch_id, "-active")
