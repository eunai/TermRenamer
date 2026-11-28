"""The Spotlight screen: a header, the Stages row, the current Stage's view and the footer.

The app owns the batch's flow: the queue, the session's settings owner, the Plan and
the Apply outcome, which it keeps in memory only. It builds the Plan, applies it and
undoes the Apply off the screen's thread, and it moves between the four Stages. Each
Stage's view lives in its own module under :mod:`termrenamer.tui.stages`, each dialog
under :mod:`termrenamer.tui.dialogs` and each view under :mod:`termrenamer.tui.views`.
Every key goes through the key table in :mod:`termrenamer.tui.keys`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.dom import DOMNode
from textual.geometry import Size
from textual.message import Message
from textual.widgets import ContentSwitcher
from textual.worker import Worker, WorkerState

from termrenamer.api.lookup import FilmLookup, TvLookup
from termrenamer.app_bootstrap import Settings, ThemeName
from termrenamer.core.apply import apply_plan
from termrenamer.core.models import (
    ApplyOutcome,
    ApplyStatus,
    Candidate,
    EntryStatus,
    Plan,
    PlanEntry,
    PlanOptions,
    ScanMode,
    Title,
    UndoOutcome,
)
from termrenamer.core.planning import (
    NO_TV_MATCH_BY_HAND,
    LeaveOut,
    PickMatch,
    PlanChange,
    PutBack,
    derive_plan,
    look_up_episodes,
    plan_queue,
    search_typed,
)
from termrenamer.core.progress import PlanEvent
from termrenamer.core.queue import SourceQueue
from termrenamer.core.undo import undo_apply
from termrenamer.session_settings import SessionSettings, locked_message
from termrenamer.tui import keys
from termrenamer.tui.dialogs import ApplyConfirm, FilePicker, FolderPicker, UndoConfirm
from termrenamer.tui.dialogs.match_picker import MatchPicker, Picked, candidate_text, picker_choices
from termrenamer.tui.log_book import LogBook, LogBookHandler
from termrenamer.tui.poster_support import PosterSource, PosterSupport
from termrenamer.tui.stage import Stage
from termrenamer.tui.stages import AppliedStage, PlanStage, PreviewStage, QueueStage, StageView
from termrenamer.tui.stages.preview import ROWS_FOR_POSTERS
from termrenamer.tui.stages.title_list_stage import TitleListStage
from termrenamer.tui.themes import THEMES
from termrenamer.tui.views import HelpView, LogsView, SettingsView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.widgets.footer import AppFooter, MessageKind
from termrenamer.tui.widgets.header import AppHeader
from termrenamer.tui.widgets.stages_row import StagesRow
from termrenamer.tui.words import (
    NO_NUL,
    NUL,
    and_list,
    error_reason,
    match_name,
    mode_label,
    noun,
    path_shown,
    plural,
    provider_name,
)
from termrenamer.util.errors import ProviderError, ValidationError
from termrenamer.util.logging import quiet_request_urls
from termrenamer.wiring import PlanningWiring

_STAGE_IDS = {
    Stage.QUEUE: "queue-stage",
    Stage.PLAN: "plan-stage",
    Stage.PREVIEW: "preview-stage",
    Stage.APPLIED: "applied-stage",
}


MIN_POSTER_SIZE = (100, ROWS_FOR_POSTERS)
"""Below this many columns or rows the poster panel is hidden, as if Posters were off."""

_BUILD = "build"
"""The worker that builds the Plan."""
_APPLY = "apply"
"""The worker that applies the Plan."""
_PICK = "pick"
"""The worker that looks up a picked TV Match's episodes."""
_UNDO = "undo"
"""The worker that undoes the last Apply."""

_REFUSED_WHILE_APPLYING = frozenset({"apply", "pick_match", "leave_out", "discard_plan"})
"""The actions that refuse while an Apply runs: each checks it, and the footer leaves
their keys out."""
_REFUSED_WHILE_UNDOING = frozenset({"undo", "new_batch"})
"""The actions that refuse while an Undo runs: each checks it, and the footer leaves
their keys out."""


def _start_folder() -> Path:
    """The folder the file and folder dialogs open in: the working folder, or the home
    folder when the working folder is gone (Apply may have removed it)."""
    try:
        return Path.cwd()
    except OSError:
        return Path.home()


@dataclass(frozen=True, slots=True)
class _BuildOutcome:
    """What a build's thread hands back: a Plan, or why there is none."""

    plan: Plan | None
    skipped: tuple[str, ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class _PickOutcome:
    """What a picked TV Match's lookups hand back: the episode titles, or why there are
    none (``episodes`` is ``None`` when the lookups were cancelled)."""

    episodes: dict[Path, str | None] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class _PendingPick:
    """A picked TV Match whose episodes are being looked up: the Plan it was picked on,
    the change waiting for the answers, the name the Title was shown under, and the lookup's cancel
    signal and worker."""

    plan: Plan
    change: PickMatch
    shown_as: str
    cancel: threading.Event
    worker: Worker[_PickOutcome] | None = None


class BuildProgress(Message):
    """An event a build reported, carried from its thread to the screen.

    ``cancel`` is that build's cancel signal, which tells its events from those of a
    build cancelled before it.
    """

    def __init__(self, event: PlanEvent, cancel: threading.Event) -> None:
        super().__init__()
        self.event = event
        self.cancel = cancel


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
        *,
        poster_support: PosterSupport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        for theme in THEMES.values():
            self.register_theme(theme)
        self._wiring = wiring
        self.poster_support = poster_support or PosterSupport()
        """Whether this run can draw Posters, checked at start (none by default)."""
        image, store = self.poster_support.image, wiring.posters
        self._posters: PosterSource | None = (
            PosterSource(store=store, image=image) if image is not None and store else None
        )
        """Where Posters come from in this run, when it can show them; one for the run, so
        a failed Poster is remembered for every panel."""
        self.session_settings = SessionSettings(settings, keyed=wiring.keyed_providers())
        self.session_settings.add_listener(self._on_plan_setting_changed)
        self.session_settings.add_theme_listener(self._use_theme)
        self.session_settings.add_poster_listener(lambda _shown: self._show_posters())
        self.theme = THEMES[self.session_settings.theme].name
        self.queue = SourceQueue()
        self.log_book = LogBook()
        self.stage = Stage.QUEUE
        self.plan: Plan | None = None
        """The Plan the Preview shows, or ``None``."""
        self.outcome: ApplyOutcome | None = None
        """What the last Apply did, while the Applied Stage shows it and Undo has not
        run; kept in memory only."""
        self._applying = False
        self._undoing = False
        self._cancel: threading.Event | None = None
        self._build_worker: Worker[_BuildOutcome] | None = None
        """The running build's cancel signal and worker, or ``None`` while no build runs.
        A cancelled build's thread may still finish a lookup; what it reports is dropped."""
        self._pick: _PendingPick | None = None
        """The picked TV Match whose episodes are being looked up, or ``None``."""
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
        # A dialog or view over the main screen pauses its poster panel.
        self.screen_change_signal.subscribe(self, lambda _screen: self._show_posters())

    def on_unmount(self) -> None:
        root = logging.getLogger()
        if self._log_handler is not None:
            root.removeHandler(self._log_handler)
        for handler in self._removed_handlers:
            root.addHandler(handler)

    def on_resize(self, event: events.Resize) -> None:
        # This runs before Textual's own handler, so ``self.size`` is still the old size.
        self._show_posters(event.size)
        self._refresh_chrome()

    @property
    def stage_view(self) -> StageView:
        """The view of the current Stage."""
        return self.query_one(f"#{_STAGE_IDS[self.stage]}", StageView)

    def _show_stage(self, stage: Stage) -> None:
        self.stage = stage
        self.query_one(ContentSwitcher).current = _STAGE_IDS[stage]
        self._show_posters()
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
        """Show ``text`` on the message line and keep it in the Logs.

        The line is the main screen's, so a message said while a view is open is
        there when the view closes.
        """
        self.screen_stack[0].query_one(AppFooter).show_message(text, kind)
        self._messages.log(kind.level, text)

    # -------------------------------------------------------------------- keys

    def footer_keys(self) -> list[keys.Key]:
        """The keys that work at the current Stage right now, in the table's order.

        A key whose action refuses while an Apply or an Undo runs, or that the lock
        refuses, is left out until it works again.
        """
        view = self.stage_view
        shown = []
        for key in keys.KEYS:
            if self.stage not in key.stages or not key.bindings:
                continue
            actions = [action for _name, action in key.bindings]
            if key.guarded and self.session_settings.locked:
                continue  # refused with the lock's message
            if any(self._refused_now(a) for a in actions):
                continue
            if all(self._target(a) is not None and view.key_enabled(a) for a in actions):
                if self._pick is not None and "discard_plan" in actions:
                    key = replace(key, hint="Abandon change")  # what esc does meanwhile
                if "leave_out" in actions and self._selected_is_left_out():
                    key = replace(key, hint="Put back")  # what x does to it
                shown.append(key)
        return shown

    def _selected_is_left_out(self) -> bool:
        """Whether the Preview's selected file is left out, so ``x`` puts it back."""
        video = self.query_one(PreviewStage).selected_file
        return video is not None and video.status is EntryStatus.LEFT_OUT

    def _refused_now(self, action: str) -> bool:
        """Whether ``action`` refuses now because an Apply or an Undo runs."""
        if self._applying:
            return action in _REFUSED_WHILE_APPLYING
        if self._undoing:
            return action in _REFUSED_WHILE_UNDOING
        return False

    def _locked_message(self, what: str) -> str:
        """Why ``what`` (such as "Mode") cannot change now that the settings are locked."""
        if self._pick is not None:
            return (
                f"{what} cannot change while the new Match's episodes are looked up. "
                "esc abandons the change."
            )
        return locked_message(what)

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
                self.say(self._locked_message(key.guarded), MessageKind.WARNING)
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
        self.push_screen(FilePicker(_start_folder()), self._source_picked)

    def action_add_folder(self) -> None:
        """Open the folder dialog; the picked folder is queued, Escape changes nothing."""
        self.push_screen(FolderPicker(_start_folder()), self._source_picked)

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
        owner = self.session_settings
        root = owner.destination_root(owner.mode)
        reason = NO_NUL if root is not None and NUL in str(root) else None
        if reason is None:
            try:
                options = owner.plan_options()
            except (OSError, RuntimeError, ValueError) as exc:  # the root cannot be resolved
                reason = error_reason(exc)
        if reason is not None:
            shown = path_shown(root) if root is not None else "not set"
            self.say(
                f"The {mode_label(owner.mode)} Destination root {shown} cannot be used: "
                f"{reason}. No Plan was built.",
                MessageKind.ERROR,
            )
            return
        self.session_settings.lock()
        self.query_one(PlanStage).start(options.provider_id, options.mode)
        self._show_stage(Stage.PLAN)
        self.say("Building the Plan…")
        self._cancel = threading.Event()
        self._build_worker = self._build(self.queue.sources, options, self._cancel)

    @work(thread=True, group="build", exit_on_error=False, name=_BUILD)
    def _build(
        self, sources: tuple[Path, ...], options: PlanOptions, cancel: threading.Event
    ) -> _BuildOutcome:
        def post(event: PlanEvent) -> None:
            self.post_message(BuildProgress(event, cancel))

        try:
            lookup = self._wiring.resolve(
                mode=options.mode, provider_id=options.provider_id, cancel=cancel
            )
            build = plan_queue(sources, options, lookup, listener=post, cancel=cancel)
        except (ValidationError, ProviderError) as exc:
            return _BuildOutcome(plan=None, skipped=(), error=str(exc))
        if build is None or not build.plan.entries:
            skipped = build.messages if build is not None else ()
            return _BuildOutcome(plan=None, skipped=skipped, error=None)
        return _BuildOutcome(plan=build.plan, skipped=build.messages, error=None)

    def on_build_progress(self, message: BuildProgress) -> None:
        if message.cancel is self._cancel and self.stage is Stage.PLAN:
            self.query_one(PlanStage).report(message.event)

    def on_plan_stage_cancel_requested(self, _message: PlanStage.CancelRequested) -> None:
        """Escape during the build: no Plan, the queue kept, the settings free again.

        A lookup already under way finishes on the build's thread; its answer, and
        anything else that build reports, is dropped.
        """
        if self._cancel is None:
            return
        self._cancel.set()
        self._end_build()
        self._show_stage(Stage.QUEUE)
        self.say("Plan cancelled. Nothing was renamed.")

    def _end_build(self) -> None:
        self._cancel = None
        self._build_worker = None
        self.query_one(PlanStage).stop()
        self.session_settings.unlock()

    def _build_finished(self, outcome: _BuildOutcome) -> None:
        self._end_build()
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
        if self._refused_now("discard_plan"):
            return
        if self._pick is not None:
            self._abandon_pick()
            return
        self.plan = None
        self._show_stage(Stage.QUEUE)
        self.say("Plan discarded. Nothing was renamed.")

    def action_leave_out(self) -> None:
        """Leave the selected video out of the Plan with its Sidecars, or put it back.

        Either change derives a new Plan, which the Preview shows with the same file
        selected. Any video can be left out, one with no match or not recognised too,
        and it stays left out through Change match until it is put back. A failure to
        test the new names on disk changes nothing: the Plan shown stays.
        """
        plan = self.plan
        preview = self.query_one(PreviewStage)
        video = preview.selected_file
        if (
            plan is None
            or video is None
            or self._refused_now("leave_out")
            or self._refuse_while_picking()
        ):
            return
        change: PlanChange
        if video.status is EntryStatus.LEFT_OUT:
            change, said = PutBack(video), "Put back in the Plan."
        else:
            change = LeaveOut(video)
            said = "Left out of the Plan: Apply does not touch this file."
        try:
            derived = derive_plan(plan, change)
        except OSError as exc:
            self.say(f"The new names could not be checked on disk: {exc}", MessageKind.ERROR)
            return
        self.plan = derived
        preview.show_plan(self.plan, keep_selection=True)
        self.say(said)

    # ------------------------------------------------------- the Match picker

    def action_pick_match(self) -> None:
        """Open the Match picker for the selected Title, or for a not recognised film.

        Nothing changes until a Candidate is picked; then a new Plan is derived, for TV
        after the picked show's episodes are looked up off the screen's thread.
        """
        plan = self.plan
        row = self.query_one(PreviewStage).selected_row
        if (
            plan is None
            or row is None
            or self._refused_now("pick_match")
            or self._refuse_while_picking()
        ):
            return
        mode = plan.mode
        target: Title | PlanEntry
        current: Candidate | None
        found: tuple[Candidate, ...]
        if row.title is None:
            if mode is ScanMode.TV:
                self.say(
                    NO_TV_MATCH_BY_HAND,
                    MessageKind.WARNING,
                )
                return
            target = row.files[0]
            name, now = target.source.name, f"Not recognised: {target.source.name}"
            current, found, typed = None, (), target.source.stem
        else:
            target = title = row.title
            name = match_name(title, mode)
            current = title.match
            found = (title.match, *title.candidates) if title.match is not None else ()
            now = f"Now: {candidate_text(title.match)}" if title.match else "No match found."
            typed = title.name
            if mode is ScanMode.FILM and title.year is not None:
                typed = f"{title.name} {title.year}"
        try:
            lookup = self._wiring.resolve(mode=mode, provider_id=plan.options.provider_id)
        except ValidationError as exc:
            self.say(str(exc), MessageKind.ERROR)
            return

        def search(text: str) -> tuple[Candidate, ...]:
            return search_typed(text, mode, lookup)

        picker = MatchPicker(
            heading=f"Pick a match for {name} · {provider_name(plan.options.provider_id)}",
            now=now,
            current=current,
            found=found,
            search=search,
            typed=typed,
            typing=not picker_choices(current, found),
            posters=self._poster_source(),
            provider_id=plan.options.provider_id,
        )

        def picked(answer: Picked | None) -> None:
            self._match_picked(plan, target, name, lookup, answer)

        self.push_screen(picker, picked)

    def _refuse_while_picking(self) -> bool:
        """Whether a picked Match's episodes are being looked up, saying so when they are.

        The Preview hides Apply, Leave out and Change match meanwhile; this refuses
        such a key or button press that still reaches the app."""
        if self._pick is None:
            return False
        self.say("Looking up the episodes for the new Match. esc abandons the change.")
        return True

    def _match_picked(
        self,
        plan: Plan,
        target: Title | PlanEntry,
        shown_as: str,
        lookup: TvLookup | FilmLookup,
        answer: Picked | None,
    ) -> None:
        if answer is None or self.plan is not plan:
            return
        current = target.match if isinstance(target, Title) else None
        if current is not None and answer.match.id == current.id:
            self.say("Kept the current match.", MessageKind.DIM)
            return
        change = PickMatch(target, answer.match, found=answer.found)
        if plan.mode is ScanMode.FILM or not isinstance(target, Title):
            self._use_pick(plan, change, shown_as)
            return
        assert isinstance(lookup, TvLookup)
        cancel = threading.Event()
        self.session_settings.lock()
        self.query_one(PreviewStage).mark_looking_up()
        self._pick = _PendingPick(plan=plan, change=change, shown_as=shown_as, cancel=cancel)
        worker = self._look_up_pick(plan, target, answer.match, lookup, cancel)
        self._pick = replace(self._pick, worker=worker)
        self.say(
            f"Looking up the episodes of {candidate_text(answer.match)}… esc abandons the change."
        )

    @work(thread=True, group=_PICK, exit_on_error=False, name=_PICK)
    def _look_up_pick(
        self,
        plan: Plan,
        title: Title,
        show: Candidate,
        lookup: TvLookup,
        cancel: threading.Event,
    ) -> _PickOutcome:
        try:
            episodes = look_up_episodes(plan, title, show, lookup, cancel=cancel)
        except ProviderError as exc:
            return _PickOutcome(episodes=None, error=str(exc))
        return _PickOutcome(episodes=episodes, error=None)

    def _pick_looked_up(self, outcome: _PickOutcome) -> None:
        pick = self._pick
        if pick is None:
            return
        self._end_pick()
        if outcome.error is not None or outcome.episodes is None:
            self.query_one(PreviewStage).show_plan(pick.plan, keep_selection=True)
            if outcome.error is not None:
                self.say(f"{outcome.error} The Plan is unchanged.", MessageKind.ERROR)
            return
        self._use_pick(pick.plan, replace(pick.change, episodes=outcome.episodes), pick.shown_as)

    def _abandon_pick(self) -> None:
        """Escape during a picked Match's lookups: the old Plan stays. A lookup already
        under way finishes on its thread, and its answer is dropped."""
        pick = self._pick
        if pick is None:
            return
        pick.cancel.set()
        self._end_pick()
        self.query_one(PreviewStage).show_plan(pick.plan, keep_selection=True)
        self.say("Match change abandoned. The Plan is unchanged.")

    def _end_pick(self) -> None:
        self._pick = None
        self.session_settings.unlock()

    def _use_pick(self, plan: Plan, change: PickMatch, shown_as: str) -> None:
        """Show the Plan ``plan`` becomes with ``change``, the same Title selected."""
        preview = self.query_one(PreviewStage)
        try:
            derived = derive_plan(plan, change)
        except OSError as exc:
            preview.show_plan(plan, keep_selection=True)
            self.say(f"The new names could not be checked on disk: {exc}", MessageKind.ERROR)
            return
        except ValueError as exc:  # a change the Plan refuses; the screen offers none
            self._messages.warning("Match change refused: %s", exc)
            preview.show_plan(plan, keep_selection=True)
            self.say(f"{exc} The Plan is unchanged.", MessageKind.ERROR)
            return
        self.plan = derived
        preview.show_plan(derived, keep_selection=True)
        self.say(f"{shown_as} now matches {match_name(change.match, plan.mode)}.")

    def action_apply(self) -> None:
        """Open the Apply confirm; only its yes applies the Plan."""
        plan = self.plan
        if plan is None or self._refused_now("apply") or self._refuse_while_picking():
            return
        self.push_screen(ApplyConfirm(plan), self._apply_answered)

    def _apply_answered(self, yes: bool | None) -> None:
        plan = self.plan
        if not yes or plan is None:
            self.say("Nothing was renamed.", MessageKind.DIM)
            return
        self._applying = True
        self.session_settings.lock()
        self.say("Applying the Plan…")
        self._apply(plan)
        self._refresh_chrome()

    @work(thread=True, exclusive=True, group="batch", exit_on_error=False, name=_APPLY)
    def _apply(self, plan: Plan) -> tuple[Plan, ApplyOutcome]:
        return plan, apply_plan(plan, confirmed=True)

    def _apply_finished(self, plan: Plan, outcome: ApplyOutcome) -> None:
        self._applying = False
        self.session_settings.unlock()
        self.plan = None
        self.outcome = outcome
        for result in outcome.results:
            target = f" → {result.destination}" if result.destination is not None else ""
            self._messages.info(
                "%s %s%s: %s", result.status.value, result.source, target, result.reason
            )
        for result in outcome.stragglers:
            self._messages.info(
                "Straggler %s %s → %s: %s",
                result.status.value,
                result.source,
                result.destination,
                result.reason,
            )
        for path in outcome.files_left_behind:
            self._messages.warning(
                "A copy Apply made could not be removed after its move failed: %s", path
            )
        applied = self.query_one(AppliedStage)
        applied.show_results(plan, outcome)
        self._show_stage(Stage.APPLIED)
        counts = applied.counts
        failed = counts is not None and counts.anything_failed
        self.say(
            "Applied." if failed else "Applied. Nothing failed.",
            MessageKind.WARNING if failed else MessageKind.INFO,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name == _UNDO:
            self._undo_state_changed(event)
            return
        if worker.name == _PICK:
            self._pick_worker_changed(event)
            return
        if worker.name not in (_BUILD, _APPLY):
            return
        if worker.name == _BUILD and worker is not self._build_worker:
            return  # a cancelled build
        if event.state is WorkerState.SUCCESS:
            if worker.name == _BUILD and isinstance(worker.result, _BuildOutcome):
                self._build_finished(worker.result)
            elif worker.name == _APPLY and isinstance(worker.result, tuple):
                self._apply_finished(*worker.result)
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            what = "Plan" if worker.name == _BUILD else "Apply"
            if worker.name == _BUILD:
                self._end_build()
                self._show_stage(Stage.QUEUE)
            else:
                self._applying = False
                self.session_settings.unlock()
            self.say(f"{what} failed: {worker.error}", MessageKind.ERROR)
            self._refresh_chrome()

    def _pick_worker_changed(self, event: Worker.StateChanged) -> None:
        pick, worker = self._pick, event.worker
        if pick is None or worker is not pick.worker:
            return  # an abandoned change
        if event.state is WorkerState.SUCCESS and isinstance(worker.result, _PickOutcome):
            self._pick_looked_up(worker.result)
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            self._pick_looked_up(
                _PickOutcome(episodes=None, error=f"Lookup failed: {worker.error}")
            )
        self._refresh_chrome()

    # -------------------------------------------------------------- Applied

    def action_new_batch(self) -> None:
        if self._refused_now("new_batch"):
            self.say("Undo is putting the files back; wait for it to finish.", MessageKind.WARNING)
            return
        self.queue.clear()
        self.outcome = None
        self.query_one(QueueStage).show_queue(())
        self._show_stage(Stage.QUEUE)
        self.say("Ready for a new batch.")

    def on_applied_stage_undo_requested(self, _message: AppliedStage.UndoRequested) -> None:
        """``u``: open the Undo confirm, when the last Apply has anything to put back."""
        applied = self.query_one(AppliedStage)
        if self._refused_now("undo") or self.stage is not Stage.APPLIED:
            return
        if self.outcome is None or not applied.undo_offered:
            self.say(
                "Apply moved nothing and made no folder, so there is nothing to undo.",
                MessageKind.DIM,
            )
            return
        self.push_screen(UndoConfirm(self.outcome), self._undo_answered)

    def _undo_answered(self, yes: bool | None) -> None:
        outcome = self.outcome
        if not yes or outcome is None or self.stage is not Stage.APPLIED:
            self.say("The Apply is kept.", MessageKind.DIM)
            return
        # Offered once: from here this outcome is never undone again.
        self.outcome = None
        self.query_one(AppliedStage).offer_undo(False)
        self._undoing = True
        self.session_settings.lock()
        self.say("Putting the files back…")
        self._undo(outcome)
        self._refresh_chrome()

    @work(thread=True, exclusive=True, group="batch", exit_on_error=False, name=_UNDO)
    def _undo(self, outcome: ApplyOutcome) -> tuple[ApplyOutcome, UndoOutcome]:
        return outcome, undo_apply(outcome)

    def _undo_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is WorkerState.SUCCESS and isinstance(event.worker.result, tuple):
            self._undo_finished(*event.worker.result)
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            self._undoing = False
            self.session_settings.unlock()
            self.say(
                f"Undo stopped: {event.worker.error}. Some files may be back already.",
                MessageKind.ERROR,
            )
            self._refresh_chrome()

    def _undo_finished(self, applied: ApplyOutcome, undone: UndoOutcome) -> None:
        """Log each file put back and each left with its reason, then show the queue."""
        self._undoing = False
        self.session_settings.unlock()
        for result in undone.results:
            if result.status is ApplyStatus.RENAMED:
                self._messages.info("Put back %s → %s", result.source, result.destination)
            else:
                self._messages.warning(
                    "Left %s (its old place %s): %s",
                    result.source,
                    result.destination,
                    result.reason,
                )
        for folder in undone.folders_made_again:
            self._messages.info("Made again: %s", folder)
        for folder in undone.emptied_folders_removed:
            self._messages.info("Removed, as Undo left it empty: %s", folder)
        for path in applied.files_left_behind:
            self._messages.warning(
                "Left to you: %s, a copy Apply made and could not remove; its source is "
                "still at its old place",
                path,
            )
        for path in undone.files_left_behind:
            self._messages.warning(
                "Left to you: %s, a copy Undo made and could not remove; the file is still "
                "at its new place",
                path,
            )
        self.query_one(QueueStage).show_queue(self.queue.sources)
        self._show_stage(Stage.QUEUE)
        put_back = f"Undo put {plural(undone.put_back, 'file')} back"
        if not undone.put_back and (removed := len(undone.emptied_folders_removed)):
            them = "the folder" if removed == 1 else f"the {removed} folders"
            put_back = f"Undo removed {them} Apply made"
        if undone.not_put_back:
            self.say(
                f"{put_back} and left {undone.not_put_back}: l shows why.", MessageKind.WARNING
            )
        else:
            self.say(f"{put_back}. Nothing was left.")

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

    # ----------------------------------------------------------- Posters

    @property
    def posters_unavailable(self) -> str | None:
        """Why this run cannot show Posters, or ``None`` when it can."""
        if not self.poster_support.available:
            return self.poster_support.reason
        if self._wiring.posters is None:
            return "no poster store is set up"
        return None

    def _poster_source(self, size: Size | None = None) -> PosterSource | None:
        """Where Posters come from while the panel is shown, or ``None`` while it is not:
        Posters unavailable or hidden, or the screen (``size``, or the app's) below the
        size limit."""
        if self._posters is None or not self.session_settings.show_posters:
            return None
        if self.posters_too_small(size) is not None:
            return None
        return self._posters

    def posters_too_small(self, size: Size | None = None) -> str | None:
        """The size Posters need when the screen (``size``, or the app's) is smaller, as
        "at least 100 columns by 35 rows", or ``None`` when it is large enough."""
        width, height = size or self.size
        columns, rows = MIN_POSTER_SIZE
        if width < columns or height < rows:
            return f"at least {columns} columns by {rows} rows"
        return None

    def _show_posters(self, size: Size | None = None) -> None:
        """Show or hide the poster panel on the main screen, under any open view too.

        Only the current Stage's panel draws Posters, and only while nothing covers the
        main screen; the others are paused.
        """
        if not self.screen_stack:
            return
        source = self._poster_source(size)
        covered = not self._on_main_screen()
        current = self.stage_view
        for view in self.screen_stack[0].query(TitleListStage):
            view.show_posters(source, paused=covered or view is not current)
        for screen in self.screen_stack[1:]:
            if isinstance(screen, MatchPicker):
                screen.use_posters(source)

    def action_toggle_posters(self) -> None:
        """``i``: hide or show Posters for the session; when unavailable, say why."""
        why = self.posters_unavailable
        if why is not None:
            self.say(f"Posters are unavailable: {why}.", MessageKind.WARNING)
            return
        owner = self.session_settings
        owner.set_show_posters(not owner.show_posters)
        if isinstance(self.screen, SettingsView):
            self.screen.show_values()
        if not owner.show_posters:
            self.say("Posters hidden (i shows them).")
        elif (needed := self.posters_too_small()) is not None:
            self.say(f"Posters on. They show when the screen is {needed}.", MessageKind.DIM)
        else:
            self.say("Posters shown.")

    # ------------------------------------------------------------- views

    def action_open_settings(self) -> None:
        self.push_screen(
            SettingsView(
                self.session_settings,
                self.posters_unavailable,
                posters_need=self.posters_too_small(),
            )
        )

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
        quiet_request_urls()
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
