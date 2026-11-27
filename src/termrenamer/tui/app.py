"""Textual application: split layout with tabbed log panel."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import work
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
from textual.worker import Worker, WorkerState
from textual_fspicker import FileOpen, SelectDirectory

from termrenamer.app_bootstrap import Settings
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyResult,
    ApplyStatus,
    EntryStatus,
    Plan,
    PlanEntry,
    PlanOptions,
    ScanMode,
)
from termrenamer.core.planning import plan_queue
from termrenamer.core.queue import SourceQueue
from termrenamer.session_settings import SessionSettings
from termrenamer.tui.screens import AddSourceQuickPick, HelpScreen, SettingsScreen
from termrenamer.tui.widgets.activity_pane import ActivityPane
from termrenamer.tui.widgets.mode_provider_bar import (
    ModeProviderBar,
    OpenSettingsRequested,
    ProviderChanged,
    ScanModeChanged,
)
from termrenamer.util.errors import ProviderError, ValidationError
from termrenamer.wiring import PlanningWiring

_LOCKED_MESSAGE = "[yellow]{what} cannot change while a Plan is being built or applied.[/yellow]"


@dataclass(frozen=True, slots=True)
class _BuildPlanWorkResult:
    """Outcome of :meth:`TermRenamerApp._run_build_plan_thread` (worker thread)."""

    log_messages: tuple[str, ...]
    plan: Plan | None


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
    entries: tuple[PlanEntry, ...],
    *,
    use_destination: bool,
) -> None:
    """Fill a ``Tree`` with paths relative to each entry's ``root``, grouped by folder.

    In the destination tree an entry with no destination stays at its source, dimmed
    and marked with its status.
    """
    tree.clear()
    nodes: dict[tuple[str, ...], Any] = {}
    for entry in entries:
        unnamed = use_destination and entry.destination is None
        path = entry.destination if use_destination and entry.destination else entry.source
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
        if unnamed:
            leaf_label = f"[dim]{leaf_label} ({entry.status.value})[/dim]"
        elif use_destination and entry.status is EntryStatus.NAME_TAKEN:
            leaf_label = f"{leaf_label} [dim]({entry.status.value})[/dim]"
        parent_node.add_leaf(leaf_label)
    tree.root.expand_all()


class TermRenamerApp(App[None]):
    """TUI: single ``#plan_panel`` column with a queue-driven action bar.

    One primary panel hosts the plan-hint → Source/Destination trees → six-button
    ``#action-bar``; a bottom ``TabbedContent`` holds the Activity / Logs panes;
    ``ModeProviderBar`` docks above the ``Footer``. Textual's built-in command
    palette (Ctrl+P) is disabled so the ``p`` binding remains a plain provider
    toggle.

    Sources are ingested via ``textual-fspicker``: the ``+ folder`` /
    ``+ file`` buttons (or ``Ctrl+F`` → :class:`AddSourceQuickPick`) push a
    ``SelectDirectory`` / ``FileOpen`` modal and add the picked path to
    :attr:`queue`. Building calls :func:`~termrenamer.core.planning.plan_queue`
    with the queue and the plan options of :attr:`session_settings`, the
    session's settings owner, which :class:`SettingsScreen` (**Ctrl+,**) and the
    mode/provider bar read and write. A change to a setting a Plan is built with
    discards the Plan and keeps the queue.
    """

    TITLE = "TermRenamer"
    CSS_PATH = "theme.tcss"
    # Disable Textual's built-in command palette (Ctrl+P); plain ``p`` remains
    # Toggle Provider.
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

    current_plan: reactive[Plan | None] = reactive(None)

    def __init__(
        self,
        wiring: PlanningWiring,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._wiring = wiring
        self.session_settings = SessionSettings(settings)
        self.session_settings.add_listener(self._on_plan_setting_changed)
        self.queue = SourceQueue()
        self.theme = "gruvbox"
        self._rename_working: bool = False

    @property
    def scan_mode(self) -> ScanMode:
        """The session's Mode, as the settings owner holds it."""
        return self.session_settings.mode

    @property
    def provider_id(self) -> str:
        """The session's Provider id, as the settings owner holds it."""
        return self.session_settings.provider_id

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
            yield ModeProviderBar(id="mode-bar", keyed=self._wiring.keyed_providers())
        yield Footer()

    def _refused_while_locked(self, what: str) -> bool:
        """Say so and refuse while a Plan is being built or applied."""
        if self.session_settings.locked:
            self._log_line(_LOCKED_MESSAGE.format(what=what))
            return True
        return False

    def action_toggle_mode(self) -> None:
        if self._refused_while_locked("Mode"):
            return
        self.query_one("#mode-bar", ModeProviderBar).toggle_mode()

    def action_toggle_provider(self) -> None:
        if self._refused_while_locked("Provider"):
            return
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
        if self._refused_while_locked("Settings"):
            return
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
        self.session_settings.set_mode(event.mode)

    def on_provider_changed(self, event: ProviderChanged) -> None:
        self.session_settings.set_provider(event.provider_id)

    def _on_plan_setting_changed(self, setting: str) -> None:
        """A setting a Plan is built with changed: discard the Plan, keep the queue."""
        if self.current_plan is None:
            return
        self.current_plan = None
        self._clear_plan_trees()
        self._set_confirm_buttons(enabled=False)
        self._refresh_source_tree()
        self._log_line(
            f"[yellow]Plan discarded: {setting} changed. The queue is kept; "
            "build the Plan again.[/yellow]",
        )

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
        """Push ``SelectDirectory``; the callback adds the path to the queue."""
        self.push_screen(SelectDirectory(str(Path.cwd())), self._on_folder_picked)

    def _open_file_picker(self) -> None:
        """Push ``FileOpen``; the callback adds the path to the queue."""
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
        """Add a picked path to the queue and refresh the dependent state."""
        try:
            resolved = self.queue.add(path)
        except OSError as exc:
            self._log_line(f"[red]Could not add {kind} {path}: {exc}[/red]")
            return
        except ValidationError as exc:
            self._log_line(f"[yellow]{exc}[/yellow]")
            return
        self._log_line(f"[bold]Queued {kind}:[/bold] {resolved}")
        self.current_plan = None
        self._clear_plan_trees()
        self._refresh_source_tree()

    def _clear_queue(self) -> None:
        if not self.queue:
            self._log_line("[dim]Queue is already empty.[/dim]")
            return
        self.queue.clear()
        self.current_plan = None
        self._clear_plan_trees()
        self._refresh_source_tree()
        self._log_line("[bold]Queue cleared.[/bold]")

    def _refresh_source_tree(self) -> None:
        """Rebuild the ``#source-tree`` view from the current queue."""
        tree = self.query_one("#source-tree", Tree)
        tree.clear()
        tree.root.label = "Queue"
        if not self.queue:
            tree.root.add_leaf("(empty — press + folder or + file to add sources)")
            tree.root.expand()
            return
        for entry in self.queue.sources:
            try:
                if entry.is_dir():
                    label = f"[bold]{entry.name or str(entry)}[/bold]/"
                    tree.root.add_leaf(f"{label}  [dim]{entry}[/dim]")
                else:
                    tree.root.add_leaf(f"{entry.name}  [dim]{entry.parent}[/dim]")
            except OSError as exc:
                tree.root.add_leaf(f"[red]{entry}[/red]  [dim]({exc})[/dim]")
        tree.root.expand()

    def action_build_plan(self) -> None:
        """Build the Plan from the queue and the plan options (preview only).

        Planning runs in a **thread worker** so Provider HTTP and filesystem stat
        work do not block the Textual event loop (see :meth:`_run_build_plan_thread`).
        """
        if self._rename_working:
            return
        if not self.queue:
            self._log_line(
                "[yellow]Queue is empty — press + folder / + file (or Ctrl+F) first.[/yellow]",
            )
            return
        sources = self.queue.sources
        options = self.session_settings.plan_options()
        self._begin_rename_work()
        self._log_line("[dim]Building plan…[/dim]")
        self._run_build_plan_thread(sources, options)

    @work(exclusive=True, thread=True, group="rename", exit_on_error=False, name="tr_build_plan")
    def _run_build_plan_thread(
        self, sources: tuple[Path, ...], options: PlanOptions
    ) -> _BuildPlanWorkResult:
        """Call the core entry point off the UI thread; report what it returns."""
        try:
            provider = self._wiring.resolve(mode=options.mode, provider_id=options.provider_id)
            build = plan_queue(sources, options, provider)
        except (ValidationError, ProviderError) as exc:
            return _BuildPlanWorkResult((f"[red]{exc}[/red]",), None)
        except Exception as exc:
            return _BuildPlanWorkResult((f"[red]Plan failed: {exc}[/red]",), None)

        log_lines = [f"[yellow]{message}[/yellow]" for message in build.messages]
        if not build.plan.entries:
            log_lines.append(
                "[yellow]No plan could be built from the current queue.[/yellow]",
            )
            return _BuildPlanWorkResult(tuple(log_lines), None)
        log_lines.append(
            f"[green]Plan built:[/green] {len(build.plan.entries)} operation(s). "
            "Review the preview above, then press Confirm apply or Cancel.",
        )
        return _BuildPlanWorkResult(tuple(log_lines), build.plan)

    @work(exclusive=True, thread=True, group="rename", exit_on_error=False, name="tr_apply_plan")
    def _run_apply_plan_thread(self, plan: Plan) -> list[ApplyResult]:
        """Apply the Plan off the UI thread, as previewed (``confirmed=True`` in core)."""
        return apply_plan(plan, confirmed=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Thread/worker completion: apply results to UI on the main thread."""
        w = event.worker
        if event.state is WorkerState.SUCCESS:
            if w.name == "tr_build_plan":
                result = w.result
                if not isinstance(result, _BuildPlanWorkResult):
                    self._end_rename_work()
                    return
                for msg in result.log_messages:
                    self._log_line(msg)
                if result.plan is not None:
                    self.current_plan = result.plan
                    self._populate_plan_trees(result.plan)
                self._end_rename_work()
            elif w.name == "tr_apply_plan":
                results = w.result
                if isinstance(results, list):
                    self._report_apply_results(results)
                self.current_plan = None
                self._set_confirm_buttons(enabled=False)
                self._refresh_source_tree()
                self._end_rename_work()
        elif event.state is WorkerState.ERROR and w.name in ("tr_build_plan", "tr_apply_plan"):
            self._end_rename_work()
            err = w.error
            if err is not None:
                label = "Plan" if w.name == "tr_build_plan" else "Apply"
                self._log_line(f"[red]{label} failed: {err}[/red]")
        elif event.state is WorkerState.CANCELLED and w.name in ("tr_build_plan", "tr_apply_plan"):
            self._end_rename_work()

    def _begin_rename_work(self) -> None:
        self._rename_working = True
        self.session_settings.lock()
        self.query_one("#mode-bar", ModeProviderBar).disabled = True
        for bid in (
            "add-files",
            "add-folders",
            "build-plan",
            "confirm-apply",
            "cancel-plan",
            "clear-queue",
        ):
            self.query_one(f"#{bid}", Button).disabled = True

    def _end_rename_work(self) -> None:
        self._rename_working = False
        self.session_settings.unlock()
        self.query_one("#mode-bar", ModeProviderBar).disabled = False
        self.query_one("#add-files", Button).disabled = False
        self.query_one("#add-folders", Button).disabled = False
        self.query_one("#build-plan", Button).disabled = False
        self.query_one("#clear-queue", Button).disabled = False
        self._set_confirm_buttons(enabled=self.current_plan is not None)

    def _apply_current_plan(self) -> None:
        """Apply the frozen plan after explicit user confirmation."""
        if self._rename_working:
            return
        plan = self.current_plan
        if plan is None:
            self._log_line("[yellow]No plan to apply. Build a plan first.[/yellow]")
            return
        self._begin_rename_work()
        self._log_line("[bold]Applying rename plan…[/bold]")
        self._run_apply_plan_thread(plan)

    def _cancel_plan(self) -> None:
        """Discard the current plan without applying (no filesystem mutation)."""
        self.current_plan = None
        self._clear_plan_trees()
        self._set_confirm_buttons(enabled=False)
        self._refresh_source_tree()
        self._log_line("[yellow]Plan cancelled — no files were renamed.[/yellow]")

    def _report_apply_results(self, results: list[ApplyResult]) -> None:
        """Write per-operation outcomes to the log panel."""
        renamed = [r for r in results if r.status is ApplyStatus.RENAMED]
        unchanged = [r for r in results if r.status is ApplyStatus.UNCHANGED]
        skips = [r for r in results if r.status is ApplyStatus.SKIP]
        fails = [r for r in results if r.status is ApplyStatus.FAIL]

        for r in renamed:
            new_name = r.destination.name if r.destination is not None else ""
            self._log_line(f"  [green]✓[/green] {r.source.name} → {new_name}")
        for r in unchanged:
            self._log_line(f"  [dim]=[/dim] {r.source.name}: {r.reason}")
        for r in skips:
            self._log_line(f"  [yellow]⊘[/yellow] {r.source.name}: {r.reason}")
        for r in fails:
            self._log_line(f"  [red]✗[/red] {r.source.name}: {r.reason}")

        self._log_line(
            f"[bold]Apply complete:[/bold] {len(renamed)} renamed, "
            f"{len(unchanged)} unchanged, {len(skips)} skipped, {len(fails)} failed.",
        )

    def _set_confirm_buttons(self, *, enabled: bool) -> None:
        self.query_one("#confirm-apply", Button).disabled = not enabled
        self.query_one("#cancel-plan", Button).disabled = not enabled

    def _clear_plan_trees(self) -> None:
        for tid in ("#source-tree", "#dest-tree"):
            self.query_one(tid, Tree).clear()

    def _populate_plan_trees(self, plan: Plan) -> None:
        self._clear_plan_trees()
        src = self.query_one("#source-tree", Tree)
        dst = self.query_one("#dest-tree", Tree)
        _populate_plan_tree(src, plan.entries, use_destination=False)
        _populate_plan_tree(dst, plan.entries, use_destination=True)

    def _log_line(self, message: str) -> None:
        self.query_one("#log_panel", RichLog).write(message)
