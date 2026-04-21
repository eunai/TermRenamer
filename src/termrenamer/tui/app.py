"""Textual application: split layout with tabbed log panel (PH-1 / FR-009 / P0-07)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual_fspicker import FileOpen, SelectDirectory

from termrenamer.app_bootstrap import Settings
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    PlanEntryStatus,
    RenamePlan,
    RenamePlanEntry,
    ScanMode,
)
from termrenamer.core.planning import (
    build_rename_plan,
    filter_plan_to_queued_path,
    merge_rename_plans,
)
from termrenamer.tui.screens import AddSourceQuickPick, HelpScreen, SettingsScreen
from termrenamer.tui.widgets.activity_pane import ActivityPane
from termrenamer.tui.widgets.mode_provider_bar import (
    ModeProviderBar,
    OpenSettingsRequested,
    ProviderChanged,
    ScanModeChanged,
)
from termrenamer.util.errors import ApplyError, ProviderError, ValidationError
from termrenamer.wiring import PlanningWiring


class _RichLogHandler(logging.Handler):
    """Routes stdlib log records into a Textual ``RichLog`` widget.

    Installed at mount time so that httpx / adapter logs render inside
    the Logs tab instead of writing raw text to the terminal.
    """

    def __init__(self, rich_log: RichLog) -> None:
        super().__init__()
        self._rich_log = rich_log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._rich_log.write(msg)
        except Exception:
            self.handleError(record)


def _populate_plan_tree(
    tree: Tree[Any],
    entries: tuple[RenamePlanEntry, ...],
    *,
    use_destination: bool,
) -> None:
    """Fill a ``Tree`` with paths relative to each entry's ``root``, grouped by folder."""
    tree.clear()
    nodes: dict[tuple[str, ...], Any] = {}
    for entry in entries:
        path = entry.destination if use_destination else entry.source
        try:
            rel = path.relative_to(entry.root)
        except ValueError:
            rel = Path(path.name)
        parts = rel.parts
        if not parts:
            continue
        for i in range(len(parts) - 1):
            key = parts[: i + 1]
            if key not in nodes:
                parent_key = parts[:i]
                parent = nodes[parent_key] if parent_key else tree.root
                nodes[key] = parent.add(parts[i])
        parent_key = parts[:-1]
        parent_node = nodes[parent_key] if parent_key else tree.root
        leaf_label = parts[-1]
        if use_destination and entry.status is PlanEntryStatus.UNMATCHED:
            leaf_label = f"[dim]{leaf_label}[/dim]"
        parent_node.add_leaf(leaf_label)
    tree.root.expand_all()


class TermRenamerApp(App[None]):
    """TUI: single ``#plan_panel`` column with a queue-driven action bar.

    The layout mirrors the mock sandbox (``dev_textual/tui_mock/``): one primary
    panel hosts the plan-hint → Source/Destination trees → six-button
    ``#action-bar``; a bottom ``TabbedContent`` holds the Activity / Logs panes;
    ``ModeProviderBar`` docks above the ``Footer``. Textual's built-in command
    palette (Ctrl+P) is disabled so the ``p`` binding remains a plain provider
    toggle.

    Sources are ingested via ``textual-fspicker`` (Phase 2): the ``+ folder`` /
    ``+ file`` buttons (or ``Ctrl+F`` → :class:`AddSourceQuickPick`) push a
    ``SelectDirectory`` / ``FileOpen`` modal and append the picked path onto
    ``self._queue``. Planning iterates the full queue (Phase 3): per-directory
    :func:`~termrenamer.core.planning.build_rename_plan` calls are merged with
    :func:`~termrenamer.core.planning.merge_rename_plans` after resolving
    cross-root destination collisions; a queued **file** is planned from its
    parent directory then filtered to that path (
    :func:`~termrenamer.core.planning.filter_plan_to_queued_path`). Film/TV
    destination roots are edited in :class:`SettingsScreen` (**Ctrl+,**) and
    snapshot onto ``self._settings`` / session overrides — not via hidden
    on-panel fields.
    """

    TITLE = "TermRenamer"
    CSS_PATH = "theme.tcss"
    # Disable Textual's built-in command palette (Ctrl+P); plain ``p`` remains
    # Toggle Provider per the mock / dev-textual-guide §2.
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("m", "toggle_mode", "Toggle Mode"),
        ("p", "toggle_provider", "Toggle Provider"),
        ("b", "build_plan", "Build plan"),
        ("a", "toggle_bottom_tab", "Activity / Logs"),
        ("ctrl+f", "open_add_source", "Add source"),
        # F1 is conventional for Help; many terminals send Ctrl+H as ASCII 0x08
        # (Backspace), so Textual often never receives it as ctrl+h.
        ("f1", "open_help", "Help"),
        ("ctrl+comma", "open_settings", "Settings"),
        ("ctrl+q", "quit", "Quit"),
    ]

    scan_mode: reactive[ScanMode] = reactive(ScanMode.TV)
    provider_id: reactive[str] = reactive("tmdb")
    current_plan: reactive[RenamePlan | None] = reactive(None)

    def __init__(
        self,
        wiring: PlanningWiring,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._wiring = wiring
        self._settings = settings
        # Queue of user-added sources (folders or individual files). Populated
        # by the fspicker callbacks (Phase 2); fan-out planning uses the whole
        # queue (Phase 3).
        self._queue: list[Path] = []
        # Session-scoped Settings overrides written by :class:`SettingsScreen`.
        # Overrides shadow bootstrap ``Settings`` for the current process; the
        # screen also snapshots saves onto ``self._settings`` via
        # ``dataclasses.replace`` when a ``Settings`` instance exists.
        self._settings_overrides: dict[str, Path | None] = {}
        self.theme = "gruvbox"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            with Vertical(id="plan_panel"):
                yield Static(
                    "Use + file / + folder (or Ctrl+F) to queue sources, then "
                    "plan (or b). Review the preview, then apply or cancel.",
                    id="plan-hint",
                )
                yield Tree("Source", id="source-tree")
                yield Tree("Destination", id="dest-tree")
                with Horizontal(id="action-bar"):
                    yield Button("+ file", id="add-files", variant="primary")
                    yield Button("+ folder", id="add-folders", variant="primary")
                    yield Button("plan", id="build-plan", variant="primary")
                    yield Button(
                        "apply",
                        id="confirm-apply",
                        variant="success",
                        disabled=True,
                    )
                    yield Static("", classes="spacer")
                    yield Button("clear", id="clear-queue", variant="warning")
                    yield Button(
                        "cancel",
                        id="cancel-plan",
                        variant="error",
                        disabled=True,
                    )
            with TabbedContent(id="bottom-tabs"):
                with TabPane("Activity", id="tab-activity"):
                    yield ActivityPane(id="activity-pane")
                with TabPane("Logs", id="tab-logs"):
                    yield RichLog(id="log_panel", highlight=True, markup=True)
            yield ModeProviderBar(id="mode-bar")
        yield Footer()

    def action_toggle_mode(self) -> None:
        self.query_one("#mode-bar", ModeProviderBar).toggle_mode()

    def action_toggle_provider(self) -> None:
        self.query_one("#mode-bar", ModeProviderBar).cycle_provider()

    def action_toggle_bottom_tab(self) -> None:
        """Flip between Activity and Logs in the bottom tabbed region."""
        tabs = self.query_one("#bottom-tabs", TabbedContent)
        tabs.active = "tab-logs" if tabs.active == "tab-activity" else "tab-activity"

    def action_open_add_source(self) -> None:
        """Push :class:`AddSourceQuickPick`; the callback routes to folder/file picker."""
        self.push_screen(AddSourceQuickPick(), self._on_add_source_choice)

    def action_open_help(self) -> None:
        """Push the full-screen :class:`HelpScreen`."""
        self.push_screen(HelpScreen())

    def action_open_settings(self) -> None:
        """Push the full-screen :class:`SettingsScreen` (TV / Film destination tabs)."""
        self.push_screen(SettingsScreen())

    def on_mount(self) -> None:
        self._install_richlog_handler()
        self.query_one("#plan_panel", Vertical).border_title = " queue "
        self.query_one("#bottom-tabs", TabbedContent).border_title = " output "
        # Defer the initial source-tree repaint one frame: ``Tree`` wiring runs
        # its own post-mount reset after the app-level ``on_mount``, so any
        # synchronous ``add_leaf`` we issue here gets swallowed. ``call_after_refresh``
        # schedules the refresh once the compositor has finished the initial pass.
        self.call_after_refresh(self._refresh_source_tree)

    def on_open_settings_requested(self, _event: OpenSettingsRequested) -> None:
        """Bridge the bar's settings button to the settings action."""
        self.action_open_settings()

    def _install_richlog_handler(self) -> None:
        """Replace the bootstrap stderr handler with one that writes to the Logs tab."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                root.removeHandler(handler)
        rich_log = self.query_one("#log_panel", RichLog)
        rlh = _RichLogHandler(rich_log)
        rlh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"),
        )
        root.addHandler(rlh)

    def on_scan_mode_changed(self, event: ScanModeChanged) -> None:
        self.scan_mode = event.mode
        self.current_plan = None
        self._clear_plan_trees()

    def on_provider_changed(self, event: ProviderChanged) -> None:
        self.provider_id = event.provider_id
        self.current_plan = None
        self._clear_plan_trees()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "add-files":
            self._open_file_picker()
        elif bid == "add-folders":
            self._open_folder_picker()
        elif bid == "clear-queue":
            self._clear_queue()
        elif bid == "build-plan":
            self.action_build_plan()
        elif bid == "confirm-apply":
            self._apply_current_plan()
        elif bid == "cancel-plan":
            self._cancel_plan()

    def _open_folder_picker(self) -> None:
        """Push ``SelectDirectory``; the callback appends onto ``self._queue``."""
        self.push_screen(SelectDirectory(str(Path.cwd())), self._on_folder_picked)

    def _open_file_picker(self) -> None:
        """Push ``FileOpen``; the callback appends onto ``self._queue``."""
        self.push_screen(FileOpen(str(Path.cwd())), self._on_file_picked)

    def _on_folder_picked(self, path: Path | None) -> None:
        if path is None:
            return
        self._append_to_queue(path, kind="folder")

    def _on_file_picked(self, path: Path | None) -> None:
        if path is None:
            return
        self._append_to_queue(path, kind="file")

    def _on_add_source_choice(self, choice: str | None) -> None:
        """Callback from :class:`AddSourceQuickPick`; dispatches to folder/file picker."""
        if choice == "folder":
            self._open_folder_picker()
        elif choice == "file":
            self._open_file_picker()

    def _append_to_queue(self, path: Path, *, kind: str) -> None:
        """Append a picked path onto the queue and refresh the dependent state."""
        try:
            resolved = path.expanduser().resolve()
        except OSError as exc:
            self._log_line(f"[red]Could not add {kind} {path}: {exc}[/red]")
            return
        self._queue.append(resolved)
        self._log_line(f"[bold]Queued {kind}:[/bold] {resolved}")
        self.current_plan = None
        self._clear_plan_trees()
        self._refresh_source_tree()

    def _clear_queue(self) -> None:
        if not self._queue:
            self._log_line("[dim]Queue is already empty.[/dim]")
            return
        self._queue.clear()
        self.current_plan = None
        self._clear_plan_trees()
        self._refresh_source_tree()
        self._log_line("[bold]Queue cleared.[/bold]")

    def _refresh_source_tree(self) -> None:
        """Rebuild the ``#source-tree`` view from the current queue."""
        tree = self.query_one("#source-tree", Tree)
        tree.clear()
        tree.root.label = "Queue"
        if not self._queue:
            tree.root.add_leaf("(empty — press + folder or + file to add sources)")
            tree.root.expand()
            return
        for entry in self._queue:
            try:
                if entry.is_dir():
                    label = f"[bold]{entry.name or str(entry)}[/bold]/"
                    tree.root.add_leaf(f"{label}  [dim]{entry}[/dim]")
                else:
                    tree.root.add_leaf(f"{entry.name}  [dim]{entry.parent}[/dim]")
            except OSError as exc:
                tree.root.add_leaf(f"[red]{entry}[/red]  [dim]({exc})[/dim]")
        tree.root.expand()

    def _resolve_dest_folder(self, mode: ScanMode) -> Path | None:
        """Destination roots: session overrides from :class:`SettingsScreen`, then ``Settings``."""
        kind: Literal["film", "tv"] = "film" if mode is ScanMode.FILM else "tv"
        override = self._settings_overrides.get(kind)
        if override is not None:
            return override.expanduser().resolve()
        if self._settings is not None:
            settings_value = (
                self._settings.film_dest_folder
                if mode is ScanMode.FILM
                else self._settings.tv_dest_folder
            )
            if settings_value is not None:
                return settings_value.resolve()
        return None

    def action_build_plan(self) -> None:
        """Build a rename plan from ``_queue``, mode, and provider (preview only).

        Each queued **directory** becomes one :func:`build_rename_plan` call; a
        queued **file** is planned from its parent directory then narrowed with
        :func:`filter_plan_to_queued_path`. Sub-plans merge with
        :func:`merge_rename_plans` so destinations remain collision-safe
        (dev-textual-guide §4 Option A).
        """
        if not self._queue:
            self._log_line(
                "[yellow]Queue is empty — press + folder / + file (or Ctrl+F) first.[/yellow]",
            )
            return
        mode = self.scan_mode
        tv_dest = self._resolve_dest_folder(ScanMode.TV)
        film_dest = self._resolve_dest_folder(ScanMode.FILM)
        try:
            if mode is ScanMode.TV:
                tv = self._wiring.resolve_tv(provider_id=self.provider_id)
            else:
                film = self._wiring.resolve_film(provider_id=self.provider_id)
        except (ValidationError, ProviderError) as exc:
            self._log_line(f"[red]{exc}[/red]")
            return
        except Exception as exc:
            self._log_line(f"[red]Plan failed: {exc}[/red]")
            return

        subplans: list[RenamePlan] = []
        for item in self._queue:
            root = item if item.is_dir() else item.parent
            try:
                if mode is ScanMode.TV:
                    sub = build_rename_plan(
                        root=root,
                        mode=ScanMode.TV,
                        provider=tv,
                        tv_dest_root=tv_dest,
                    )
                else:
                    sub = build_rename_plan(
                        root=root,
                        mode=ScanMode.FILM,
                        provider=film,
                        film_dest_root=film_dest,
                    )
            except (ValidationError, ProviderError) as exc:
                self._log_line(f"[red]{exc}[/red]")
                return
            except Exception as exc:
                self._log_line(f"[red]Plan failed: {exc}[/red]")
                return

            if not item.is_dir():
                sub = filter_plan_to_queued_path(sub, item)
                if not sub.entries:
                    self._log_line(
                        f"[yellow]No matching entries for queued file {item}[/yellow]",
                    )
                    continue

            subplans.append(sub)

        if not subplans:
            self._log_line(
                "[yellow]No plan could be built from the current queue.[/yellow]",
            )
            return

        plan = merge_rename_plans(subplans)

        self.current_plan = plan
        self._populate_plan_trees(plan)
        self._set_confirm_buttons(enabled=True)
        self._log_line(
            f"[green]Plan built:[/green] {len(plan.entries)} operation(s). "
            "Review the preview above, then press Confirm apply or Cancel.",
        )

    def _apply_current_plan(self) -> None:
        """Apply the frozen plan after explicit user confirmation (FR-007 / P0-07)."""
        plan = self.current_plan
        if plan is None:
            self._log_line("[yellow]No plan to apply. Build a plan first.[/yellow]")
            return

        self._log_line("[bold]Applying rename plan…[/bold]")
        try:
            results = apply_plan(plan, confirmed=True)
        except (ValidationError, ApplyError) as exc:
            self._log_line(f"[red]Apply failed: {exc}[/red]")
            return
        except Exception as exc:
            self._log_line(f"[red]Apply error: {exc}[/red]")
            return

        self._report_apply_results(results)
        self.current_plan = None
        self._set_confirm_buttons(enabled=False)
        self._refresh_source_tree()

    def _cancel_plan(self) -> None:
        """Discard the current plan without applying (no filesystem mutation)."""
        self.current_plan = None
        self._clear_plan_trees()
        self._set_confirm_buttons(enabled=False)
        self._refresh_source_tree()
        self._log_line("[yellow]Plan cancelled — no files were renamed.[/yellow]")

    def _report_apply_results(self, results: list[ApplyResult]) -> None:
        """Write per-operation outcomes to the log panel."""
        successes = [r for r in results if r.status is ApplyStatus.SUCCESS]
        skips = [r for r in results if r.status is ApplyStatus.SKIP]
        fails = [r for r in results if r.status is ApplyStatus.FAIL]

        for r in successes:
            self._log_line(f"  [green]✓[/green] {r.source.name} → {r.destination.name}")
        for r in skips:
            self._log_line(f"  [yellow]⊘[/yellow] {r.source.name}: {r.reason}")
        for r in fails:
            self._log_line(f"  [red]✗[/red] {r.source.name}: {r.reason}")

        self._log_line(
            f"[bold]Apply complete:[/bold] "
            f"{len(successes)} succeeded, {len(skips)} skipped, {len(fails)} failed.",
        )

    def _set_confirm_buttons(self, *, enabled: bool) -> None:
        self.query_one("#confirm-apply", Button).disabled = not enabled
        self.query_one("#cancel-plan", Button).disabled = not enabled

    def _clear_plan_trees(self) -> None:
        for tid in ("#source-tree", "#dest-tree"):
            self.query_one(tid, Tree).clear()

    def _populate_plan_trees(self, plan: RenamePlan) -> None:
        self._clear_plan_trees()
        src = self.query_one("#source-tree", Tree)
        dst = self.query_one("#dest-tree", Tree)
        _populate_plan_tree(src, plan.entries, use_destination=False)
        _populate_plan_tree(dst, plan.entries, use_destination=True)

    def _log_line(self, message: str) -> None:
        self.query_one("#log_panel", RichLog).write(message)
