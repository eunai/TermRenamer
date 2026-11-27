"""The header: the app name, the Mode as two tabs, the Provider and the Mode's Destination root."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import ScanMode
from termrenamer.tui.words import folder_text


class AppHeader(Horizontal):
    """One line: ``TermRenamer  Mode  TV  Film    Provider  TMDB ▾ … Destination root  <path>``."""

    DEFAULT_CSS = """
    AppHeader {
        height: 1;
        background: $panel;
        padding: 0 2;
    }
    AppHeader #header-left {
        width: auto;
        height: 1;
    }
    AppHeader #header-root {
        width: 1fr;
        height: 1;
        padding: 0 0 0 4;
        text-align: right;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="header-left")
        yield Static(id="header-root")

    def show(
        self,
        *,
        mode: ScanMode,
        provider: str,
        has_key: bool,
        root: Path | None,
        folder_rename: bool,
    ) -> None:
        """Draw the header for ``mode``, ``provider`` (its name) and the Mode's ``root``."""

        def tab(label: str, on: bool) -> str:
            if on:
                return f"[b $tr-on-accent on $accent] {label} [/]"
            return f"[$foreground] {label} [/]"

        no_key = " (no key)" if not has_key else ""
        left = (
            "[b $accent]TermRenamer[/]     [$tr-dim]Mode[/] "
            f"{tab('TV', mode is ScanMode.TV)}{tab('Film', mode is ScanMode.FILM)}"
            f"    [$tr-dim]Provider[/] [$accent on $tr-button] {provider}{no_key} ▾ [/]"
        )
        self.query_one("#header-left", Static).update(left)
        if not folder_rename:
            value = "[$tr-dim]not used: Folder rename is off[/]"
        elif root is None:
            value = "[$tr-dim]not set[/]"
        else:
            value = f"[$foreground]{escape(folder_text(root))}[/]"
        self.query_one("#header-root", Static).update(f"[$tr-dim]Destination root[/] {value}")
