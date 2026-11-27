"""The Applied Stage: what Apply did, counted in videos, what it skipped, and a new batch."""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.widgets import Static

from termrenamer.core.models import ApplyResult, Plan
from termrenamer.core.title_rows import AppliedCounts, skipped_results
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.widgets.action_button import ActionButton
from termrenamer.tui.words import sidecar_skipped


class AppliedStage(StageView):
    """The counts of renamed, skipped and failed videos, and New batch."""

    DEFAULT_CSS = """
    AppliedStage #applied-body {
        height: 1fr;
        padding: 2 4 0 4;
    }
    AppliedStage #applied-title {
        text-style: bold;
        margin-bottom: 1;
    }
    AppliedStage #applied-counts {
        margin-bottom: 1;
    }
    AppliedStage #applied-skipped {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
        color: $tr-dim;
    }
    AppliedStage .buttons {
        height: 1;
    }
    AppliedStage .buttons ActionButton {
        margin: 0 2 0 0;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._counts: AppliedCounts | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="applied-body"):
            yield Static("The Plan is applied.", id="applied-title")
            yield Static("", id="applied-counts")
            yield Static("", id="applied-skipped")
            with Horizontal(classes="buttons"):
                yield ActionButton("n", "New batch", press_key="n", classes="-plain")

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
            line += f" [$tr-dim]· {counts.unchanged} already had their names[/]"
        self.query_one("#applied-counts", Static).update(line)
        videos, sidecars = skipped_results(plan, results)
        skipped = [f"{r.source.name} · {r.reason}" for r in videos]
        skipped += [sidecar_skipped(r.source, r.reason) for r in sidecars]
        self.query_one("#applied-skipped", Static).update(escape("\n".join(skipped)))
        self.query_one("#applied-title", Static).update(
            "The Plan is applied." + ("" if counts.failed else " Nothing failed.")
        )
        self.changed()

    def count_text(self) -> str:
        if self._counts is None:
            return ""
        return f"{self._counts.renamed} renamed"
