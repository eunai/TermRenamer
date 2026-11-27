"""The Spotlight screen: a header, the Stages row, the current Stage's view and the footer.

The app owns the batch's flow: the queue, the session's settings owner, the Plan and
the Apply results. It builds the Plan and applies it off the screen's thread, and it
moves between the four Stages. Each Stage's view lives in its own module under
:mod:`termrenamer.tui.stages`, each dialog under :mod:`termrenamer.tui.dialogs` and
each view under :mod:`termrenamer.tui.views`. Every key goes through the key table in
:mod:`termrenamer.tui.keys`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.dom import DOMNode
from textual.message import Message
from textual.widgets import ContentSwitcher
from textual.worker import Worker, WorkerState
from textual_fspicker import FileOpen, SelectDirectory

from termrenamer.app_bootstrap import Settings, ThemeName
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyResult,
    Plan,
    PlanOptions,
    ScanMode,
)
from termrenamer.core.planning import plan_queue
from termrenamer.core.progress import PlanEvent
from termrenamer.core.queue import SourceQueue
from termrenamer.core.title_rows import PlanCounts
from termrenamer.session_settings import SessionSettings, locked_message
from termrenamer.tui import keys
from termrenamer.tui.dialogs import ApplyConfirm
from termrenamer.tui.log_book import LogBook, LogBookHandler
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages import AppliedStage, PlanStage, PreviewStage, QueueStage, StageView
from termrenamer.tui.themes import THEMES
from termrenamer.tui.views import HelpView, LogsView, SettingsView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.footer import AppFooter, MessageKind
from termrenamer.tui.widgets.header import AppHeader
from termrenamer.tui.widgets.stages_row import StagesRow
from termrenamer.tui.words import and_list, mode_label, noun, provider_name
from termrenamer.util.errors import ProviderError, ValidationError
from termrenamer.wiring import PlanningWiring

_STAGE_IDS = {
    Stage.QUEUE: "queue-stage",
    Stage.PLAN: "plan-stage",
    Stage.PREVIEW: "preview-stage",
    Stage.APPLIED: "applied-stage",
}


_BUILD = "build"
_APPLY = "apply"
"""The names of the two workers: the build of the Plan and its Apply."""


@dataclass(frozen=True, slots=True)
class _BuildOutcome:
    """What a build's thread hands back: a Plan, or why there is none."""

    plan: Plan | None
    skipped: tuple[str, ...]
    error: str | None


class BuildProgress(Message):
    """An event a build reported, carried from its thread to the screen."""

    def __init__(self, event: PlanEvent) -> None:
        super().__init__()
        self.event = event


class LogLineAdded(Message):
    """A line was added to the log book (posted from any thread)."""


class TermRenamerApp(App[None]):
    """The TermRenamer screen. Nothing is renamed before the Apply confirmation."""

    TITLE = "TermRenamer"
    CSS_PATH = "theme.tcss"
    # Textual's command palette would take Ctrl+P; the app has no use for it.
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = keys.bindings()

    def __init__(
        self,
        wiring: PlanningWiring,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        for theme in THEMES.values():
            self.register_theme(theme)
        self._wiring = wiring
        self.session_settings = SessionSettings(settings, keyed=wiring.keyed_providers())
        self.session_settings.add_listener(self._on_plan_setting_changed)
        self.session_settings.add_theme_listener(self._use_theme)
        self.theme = THEMES[self.session_settings.theme].name
        self.queue = SourceQueue()
        self.log_book = LogBook()
        self.stage = Stage.QUEUE
        self.plan: Plan | None = None
        """The Plan the Preview shows, or ``None``."""
        self.results: tuple[ApplyResult, ...] | None = None
        """What the last Apply did, while the Applied Stage shows it."""
        self._applying = False
        self._messages = logging.getLogger("termrenamer.tui")
        self._messages.setLevel(logging.INFO)
        self._log_handler: LogBookHandler | None = None
        self._removed_handlers: list[logging.Handler] = []

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield AppHeader(id="header")
        yield StagesRow(id="stages-row")
        with ContentSwitcher(initial=_STAGE_IDS[Stage.QUEUE], id="stage-body"):
            yield QueueStage(id=_STAGE_IDS[Stage.QUEUE])
            yield PlanStage(id=_STAGE_IDS[Stage.PLAN])
            yield PreviewStage(id=_STAGE_IDS[Stage.PREVIEW])
            yield AppliedStage(id=_STAGE_IDS[Stage.APPLIED])
        yield AppFooter(id="footer")

    def on_mount(self) -> None:
        self._install_log_handler()
        self._show_stage(Stage.QUEUE)

    def on_unmount(self) -> None:
        root = logging.getLogger()
        if self._log_handler is not None:
            root.removeHandler(self._log_handler)
        for handler in self._removed_handlers:
            root.addHandler(handler)

    def on_resize(self) -> None:
        self._refresh_chrome()

    @property
    def stage_view(self) -> StageView:
        """The view of the current Stage."""
        return self.query_one(f"#{_STAGE_IDS[self.stage]}", StageView)

    def _show_stage(self, stage: Stage) -> None:
        self.stage = stage
        self.query_one(ContentSwitcher).current = _STAGE_IDS[stage]
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        """Draw the header, the Stages row and the footer for the current state."""
        if not self.screen_stack or not self.query(AppHeader):
            return
        owner = self.session_settings
        self.query_one(AppHeader).show(
            mode=owner.mode,
            provider=provider_name(owner.provider_id),
            has_key=owner.has_key(owner.provider_id),
            root=owner.destination_root(owner.mode),
            folder_rename=owner.folder_rename,
        )
        view = self.stage_view
        self.query_one(StagesRow).show(self.stage, view.count_text())
        footer = self.query_one(AppFooter)
        footer.show_lines(view.footer_lines())
        footer.show_keys(self.footer_keys())

    def on_stage_view_changed(self, _message: StageView.Changed) -> None:
        self._refresh_chrome()

    def say(self, text: str, kind: MessageKind = MessageKind.INFO) -> None:
        """Show ``text`` on the message line and keep it in the Logs."""
        self.query_one(AppFooter).show_message(text, kind)
        self._messages.log(kind.level, text)

    # -------------------------------------------------------------------- keys

    def footer_keys(self) -> list[keys.Key]:
        """The keys that work at the current Stage right now, in the table's order."""
        view = self.stage_view
        shown = []
        for key in keys.KEYS:
            if self.stage not in key.stages or not key.bindings:
                continue
            actions = [action for _name, action in key.bindings]
            if all(self._target(a) is not None and view.key_enabled(a) for a in actions):
                shown.append(key)
        return shown

    def _target(self, action: str) -> DOMNode | None:
        """Where ``action`` is implemented: the current Stage's view, else the app."""
        for node in (self.stage_view, self):
            if callable(getattr(node, f"action_{action}", None)):
                return node
        return None

    def _on_main_screen(self) -> bool:
        return self.screen is self.screen_stack[0]

    async def action_press(self, name: str) -> None:
        """Run the key table's action for the Textual key ``name`` at the current Stage.

        A key of the current Stage whose action is not built yet does nothing. A key
        of another Stage says where it works, when its action is built.
        """
        on_main = self._on_main_screen()
        wrong_stage: keys.Key | None = None
        for key, action in keys.entries_for(name):
            if not on_main and not key.anywhere:
                continue
            if key.guarded and self.session_settings.locked:
                self.say(locked_message(key.guarded), MessageKind.WARNING)
                return
            target = self._target(action)
            if on_main and self.stage not in key.stages:
                if target is not None:
                    wrong_stage = wrong_stage or key
                continue
            if target is None:
                return
            await self.run_action(action, target)
            self._refresh_chrome()
            return
        if wrong_stage is not None:
            stages = wrong_stage.stage_names
            self.say(
                f"{wrong_stage.hint} works at the {and_list(stages)} {noun(len(stages), 'Stage')}.",
                MessageKind.WARNING,
            )

    async def on_action_button_clicked(self, event: ActionButton.Clicked) -> None:
        event.stop()
        await self.action_press(event.button.press_key)

    # ------------------------------------------------------------- the queue

    def action_add_file(self) -> None:
        """Open the file dialog; the picked file is queued, Escape changes nothing."""
        self.push_screen(FileOpen(str(Path.cwd())), self._source_picked)

    def action_add_folder(self) -> None:
        """Open the folder dialog; the picked folder is queued, Escape changes nothing."""
        self.push_screen(SelectDirectory(str(Path.cwd())), self._source_picked)

    def _source_picked(self, path: Path | None) -> None:
        if path is None or self.stage is not Stage.QUEUE:
            return
        try:
            resolved = self.queue.add(path)
        except ValidationError as exc:
            self.say(str(exc), MessageKind.WARNING)
            return
        except OSError as exc:
            self.say(f"Could not queue {path}: {exc}", MessageKind.ERROR)
            return
        self.query_one(QueueStage).show_queue(self.queue.sources)
        self.say(f"Queued {resolved}.")

    def action_clear_queue(self) -> None:
        if not self.queue:
            self.say("The queue is already empty.", MessageKind.DIM)
            return
        self.queue.clear()
        self.query_one(QueueStage).show_queue(())
        self.say("Queue cleared.")

    # ----------------------------------------------------------- the build

    def action_build_plan(self) -> None:
        """Build the Plan from the queue off the screen's thread; nothing is renamed."""
        if not self.queue:
            self.say("Add a Source first (a or f).", MessageKind.WARNING)
            return
        options = self.session_settings.plan_options()
        self.session_settings.lock()
        self.query_one(PlanStage).start(provider_name(options.provider_id), options.mode)
        self._show_stage(Stage.PLAN)
        self.say("Building the Plan…")
        self._build(self.queue.sources, options)

    @work(thread=True, exclusive=True, group="batch", exit_on_error=False, name=_BUILD)
    def _build(self, sources: tuple[Path, ...], options: PlanOptions) -> _BuildOutcome:
        try:
            lookup = self._wiring.resolve(mode=options.mode, provider_id=options.provider_id)
            build = plan_queue(sources, options, lookup, listener=self._post_progress)
        except (ValidationError, ProviderError) as exc:
            return _BuildOutcome(plan=None, skipped=(), error=str(exc))
        if not build.plan.entries:
            return _BuildOutcome(plan=None, skipped=build.messages, error=None)
        return _BuildOutcome(plan=build.plan, skipped=build.messages, error=None)

    def _post_progress(self, event: PlanEvent) -> None:
        """The build's listener: carry ``event`` to the screen (called on the build's thread)."""
        self.post_message(BuildProgress(event))

    def on_build_progress(self, message: BuildProgress) -> None:
        if self.stage is Stage.PLAN:
            self.query_one(PlanStage).report(message.event)

    def _build_finished(self, outcome: _BuildOutcome) -> None:
        self.session_settings.unlock()
        for line in outcome.skipped:
            self._messages.warning(line)
        if outcome.error is not None:
            self._show_stage(Stage.QUEUE)
            self.say(f"{outcome.error} No Plan was built.", MessageKind.ERROR)
            return
        if outcome.plan is None:
            self._show_stage(Stage.QUEUE)
            self.say("No video was found in the queued Sources.", MessageKind.WARNING)
            return
        self.plan = outcome.plan
        self.query_one(PreviewStage).show_plan(outcome.plan)
        self._show_stage(Stage.PREVIEW)
        skipped = " Some Sources were skipped: l shows why." if outcome.skipped else ""
        self.say(f"Plan built. Check each Title, then enter to Apply.{skipped}")

    # ---------------------------------------------------------- the Preview

    def action_discard_plan(self) -> None:
        if self._applying:
            return
        self.plan = None
        self._show_stage(Stage.QUEUE)
        self.say("Plan discarded. Nothing was renamed.")

    def action_apply(self) -> None:
        """Open the Apply confirm; only its yes applies the Plan."""
        plan = self.plan
        if plan is None or self._applying:
            return
        counts = PlanCounts.of(plan)
        root = plan.options.destination_root
        under = f"under {root}/" if root is not None else "in their own folders"
        confirm = ApplyConfirm(
            videos=counts.to_rename,
            under=under,
            no_match=counts.no_match,
            not_recognised=counts.not_recognised,
        )
        self.push_screen(confirm, self._apply_answered)

    def _apply_answered(self, yes: bool | None) -> None:
        plan = self.plan
        if not yes or plan is None:
            self.say("Nothing was renamed.", MessageKind.DIM)
            return
        self._applying = True
        self.session_settings.lock()
        self.say("Applying the Plan…")
        self._apply(plan)

    @work(thread=True, exclusive=True, group="batch", exit_on_error=False, name=_APPLY)
    def _apply(self, plan: Plan) -> tuple[Plan, tuple[ApplyResult, ...]]:
        return plan, tuple(apply_plan(plan, confirmed=True))

    def _apply_finished(self, plan: Plan, results: tuple[ApplyResult, ...]) -> None:
        self._applying = False
        self.session_settings.unlock()
        self.plan = None
        self.results = results
        for result in results:
            target = f" → {result.destination}" if result.destination is not None else ""
            self._messages.info(
                "%s %s%s: %s", result.status.value, result.source, target, result.reason
            )
        applied = self.query_one(AppliedStage)
        applied.show_results(plan, results)
        self._show_stage(Stage.APPLIED)
        counts = applied.counts
        failed = counts is not None and counts.failed
        self.say(
            "Applied." if failed else "Applied. Nothing failed.",
            MessageKind.WARNING if failed else MessageKind.INFO,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name not in (_BUILD, _APPLY):
            return
        if event.state is WorkerState.SUCCESS:
            if worker.name == _BUILD and isinstance(worker.result, _BuildOutcome):
                self._build_finished(worker.result)
            elif worker.name == _APPLY and isinstance(worker.result, tuple):
                self._apply_finished(*worker.result)
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            self.session_settings.unlock()
            self._applying = False
            what = "Plan" if worker.name == _BUILD else "Apply"
            if worker.name == _BUILD:
                self._show_stage(Stage.QUEUE)
            self.say(f"{what} failed: {worker.error}", MessageKind.ERROR)
            self._refresh_chrome()

    # -------------------------------------------------------------- Applied

    def action_new_batch(self) -> None:
        self.queue.clear()
        self.results = None
        self.query_one(QueueStage).show_queue(())
        self._show_stage(Stage.QUEUE)
        self.say("Ready for a new batch.")

    # ----------------------------------------------------- Mode and Provider

    def action_change_mode(self) -> None:
        owner = self.session_settings
        mode = ScanMode.FILM if owner.mode is ScanMode.TV else ScanMode.TV
        self._change(lambda: owner.set_mode(mode))

    def action_change_provider(self) -> None:
        self._change(self.session_settings.next_provider)

    def _change(self, change: Callable[[], object]) -> None:
        """Change the Mode or the Provider, then say where they now stand.

        The key table refuses ``m`` and ``p`` while the settings owner is locked. When
        a Plan was discarded, the message says so instead.
        """
        had_plan = self.plan is not None
        change()
        if not had_plan:
            owner = self.session_settings
            self.say(f"Mode: {mode_label(owner.mode)}. Provider: {self._provider_text()}.")

    def _provider_text(self) -> str:
        owner = self.session_settings
        name = provider_name(owner.provider_id)
        return name if owner.has_key(owner.provider_id) else f"{name} (no key)"

    def _on_plan_setting_changed(self, setting: str) -> None:
        """A setting a Plan is built with changed: discard the Plan, keep the queue."""
        if self.plan is not None:
            self.plan = None
            self._show_stage(Stage.QUEUE)
            self.say(
                f"Plan discarded: {setting} changed. The queue is kept; build the Plan again.",
                MessageKind.WARNING,
            )
        self._refresh_chrome()

    # ------------------------------------------------------------- views

    def action_open_settings(self) -> None:
        self.push_screen(SettingsView(self.session_settings))

    def action_open_logs(self) -> None:
        self._open_view(LogsView(self.log_book))

    def action_open_help(self) -> None:
        self._open_view(HelpView())

    def _open_view(self, view: LogsView | HelpView) -> None:
        """Open ``view`` over the screen, in place of another view; never twice."""
        if type(self.screen) is type(view):
            return
        if isinstance(self.screen, (LogsView, HelpView, SettingsView)):
            self.switch_screen(view)
        else:
            self.push_screen(view)

    def _use_theme(self, theme: ThemeName) -> None:
        self.theme = THEMES[theme].name
        for view in self.query(StageView):
            view.redraw()

    # ------------------------------------------------------------- the Logs

    def _install_log_handler(self) -> None:
        """Send every log record to the log book in place of stderr, while the screen runs."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                root.removeHandler(handler)
                self._removed_handlers.append(handler)
        self._log_handler = LogBookHandler(self.log_book, self._post_log_line)
        root.addHandler(self._log_handler)

    def _post_log_line(self) -> None:
        self.post_message(LogLineAdded())

    def on_log_line_added(self, _message: LogLineAdded) -> None:
        if isinstance(self.screen, LogsView):
            self.screen.catch_up()
