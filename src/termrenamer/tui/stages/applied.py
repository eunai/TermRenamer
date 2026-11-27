"""The Applied Stage: what Apply did, counted in videos, and each file it did not rename.

The left column holds the counts and the actions (New batch; Undo once #26 builds
it). The right lists each skipped, failed and left out video with its reason, and each
Sidecar that was not renamed while its video was. Every result, Sidecars included,
is also in the Logs.
"""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import ApplyResult, ApplyStatus, Plan, PlanEntry
from termrenamer.core.title_rows import AppliedCounts
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.words import agree, folder_text, why_not_renamed

_APPLIED = frozenset({ApplyStatus.RENAMED, ApplyStatus.UNCHANGED})


class AppliedStage(StageView):
    """The counts, Undo and New batch on the left; the files not renamed on the right."""

    DEFAULT_CSS = """
    AppliedStage #applied-summary {
        width: 39;
        height: 1fr;
        padding: 1 1 0 3;
        border-right: solid $tr-line;
    }
    AppliedStage #applied-title {
        text-style: bold;
        margin-bottom: 1;
    }
    AppliedStage #applied-counts {
        margin-bottom: 2;
    }
    AppliedStage #applied-summary ActionButton {
        margin: 0 0 1 0;
    }
    AppliedStage #applied-files {
        height: 1fr;
        padding: 1 2 0 2;
    }
    AppliedStage #applied-heading {
        height: 2;
        padding: 0 2;
        border-bottom: solid $tr-line;
        text-style: bold;
    }
    AppliedStage #applied-scroll {
        height: 1fr;
        padding: 1 2 0 2;
        scrollbar-size-vertical: 1;
    }
    AppliedStage #applied-list {
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._counts: AppliedCounts | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="applied-summary"):
                yield Static("The Plan is applied.", id="applied-title")
                yield Static("", id="applied-counts")
                yield ActionButton(
                    "u", "Undo last Apply", press_key="u", id="undo", classes="-plain"
                )
                yield ActionButton("n", "New batch", press_key="n", classes="-plain")
            with Vertical(id="applied-files"):
                yield Static("", id="applied-heading")
                with VerticalScroll(id="applied-scroll"):
                    yield Static("", id="applied-list")

    def on_mount(self) -> None:
        # The Undo button shows once its key's action is built (#26).
        self.query_one("#undo").display = callable(getattr(self, "action_undo", None))

    @property
    def counts(self) -> AppliedCounts | None:
        return self._counts

    def show_results(self, plan: Plan, results: Sequence[ApplyResult]) -> None:
        counts = AppliedCounts.of(plan, results)
        self._counts = counts
        line = (
            f"[$success]{counts.renamed} renamed[/] [$tr-dim]·[/] "
            f"[$warning]{counts.skipped} skipped[/] [$tr-dim]·[/] "
            f"[{'$error' if counts.failed else '$tr-dim'}]{counts.failed} failed[/]"
        )
        if counts.unchanged:
            had = agree(counts.unchanged, "had its name", "had their names")
            line += f"\n[$tr-dim]{counts.unchanged} already {had}[/]"
        if counts.left_out:
            line += f"\n[$tr-dim]{counts.left_out} left out[/]"
        self.query_one("#applied-counts", Static).update(line)
        self.query_one("#applied-title", Static).update(
            "The Plan is applied." + ("" if counts.failed else "\nNothing failed.")
        )
        files = not_renamed(plan, results)
        self.query_one("#applied-heading", Static).update(
            f"[$foreground]Not renamed[/]  [$tr-dim]{len(files)}[/]"
        )
        self.query_one("#applied-list", Static).update(
            "\n".join(_lines_for(entry, result) for entry, result in files)
            or "[$tr-dim]Every video was renamed.[/]"
        )
        self.changed()

    def count_text(self) -> str:
        if self._counts is None:
            return ""
        return f"{self._counts.renamed} renamed"


def not_renamed(plan: Plan, results: Sequence[ApplyResult]) -> list[tuple[PlanEntry, ApplyResult]]:
    """Each video Apply skipped, failed or found left out, then each Sidecar it did not rename while
    renaming its video (or finding it already named), in Apply's order."""
    entries = {entry.source: entry for entry in plan.entries}
    status = {result.source: result.status for result in results}
    files = []
    for result in results:
        entry = entries.get(result.source)
        if entry is None or result.status in _APPLIED:
            continue
        if entry.video is None or status.get(entry.video) in _APPLIED:
            files.append((entry, result))
    return files


def _lines_for(entry: PlanEntry, result: ApplyResult) -> str:
    """Two lines: the file's name and its folder, then why it was not renamed."""
    if result.status is ApplyStatus.FAIL:
        reason, colour = f"failed: {result.reason}", "$error"
    elif result.status is ApplyStatus.LEFT_OUT:
        reason, colour = "left out of the Plan", "$tr-dim"
    else:
        # A skip for the entry's status gives the Preview's reason; a check at Apply
        # time (a changed source, a taken destination) gives Apply's.
        why = why_not_renamed(entry)
        planned = not entry.has_its_name
        reason = why if why is not None and planned else result.reason
        colour = "$warning"
    if entry.is_sidecar:
        reason = f"Sidecar not renamed: {reason}"
    source = entry.source
    return (
        f"[$foreground]{escape(source.name)}[/]  [$tr-dim]{escape(folder_text(source.parent))}[/]\n"
        f"    [{colour}]{escape(reason)}[/]"
    )
