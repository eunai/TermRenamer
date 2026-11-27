"""The Apply confirm: nothing is renamed until the person answers yes.

It returns ``True`` for ``y`` or ``enter`` and ``False`` for ``n`` or Escape. It sits
over the Title list, right of where the Poster panel goes.
"""

from __future__ import annotations

from collections import Counter

from textual.binding import Binding
from textual.content import Content
from textual.markup import escape

from termrenamer.core.models import EntryStatus, Plan
from termrenamer.core.paths import claim_key
from termrenamer.core.title_rows import PlanCounts, sidecars_skipped_alone
from termrenamer.tui.dialogs.confirm import ConfirmDialog
from termrenamer.tui.words import (
    agree,
    folder_text,
    match_name,
    plural,
    sidecar_skipped,
    why_not_renamed,
)


def confirm_lines(plan: Plan) -> tuple[str, ...]:
    """What the confirm says (Textual markup): the videos renamed and where, the videos
    skipped counted by status, the videos left out, each Sidecar skipped while its
    video moves, those that already have their names, with Folder rename on the
    Stragglers to merge and the Titles they go with, and that nothing has been renamed
    yet."""
    counts = PlanCounts.of(plan)
    root = plan.options.destination_root
    if root is not None:
        where = f"under {folder_text(root)}"
    else:
        where = agree(counts.to_rename, "in its own folder", "in their own folders")
    staying = [v for v in plan.videos if why_not_renamed(v) is not None]
    named = [v for v in staying if v.has_its_name]
    left_out = EntryStatus.LEFT_OUT
    skipped: Counter[EntryStatus] = Counter(
        v.status for v in staying if not v.has_its_name and v.status is not left_out
    )
    if skipped:
        reasons = " · ".join(f"{skipped[s]} {s.value}" for s in EntryStatus if skipped[s])
        skip = f"Skip {plural(skipped.total(), 'video')}: {reasons}"
    else:
        skip = "Skip none."
    lines = [
        f"[$foreground]Rename {plural(counts.to_rename, 'video')} {escape(where)}.[/]",
        f"[$foreground]{skip}[/]",
    ]
    if counts.left_out:
        them = agree(counts.left_out, "it", "them")
        lines.append(
            f"[$foreground]Leave out {plural(counts.left_out, 'video')}: "
            f"Apply does not touch {them}.[/]"
        )
    for sidecar in sidecars_skipped_alone(plan):
        reason = why_not_renamed(sidecar) or sidecar.status.value
        lines.append(f"[$tr-dim]{escape(sidecar_skipped(sidecar.source, reason))}[/]")
    if named:
        that = agree(len(named), "that already has its name", "that already have their names")
        lines.append(f"[$tr-dim]Leave {plural(len(named), 'video')} {that}.[/]")
    if plan.options.folder_rename:
        lines.append(f"[$tr-dim]{escape(_merge_line(plan))}[/]")
    lines += ["", "[$warning]Nothing has been renamed yet.[/]"]
    return tuple(lines)


def _merge_line(plan: Plan) -> str:
    """``Merge 2 Stragglers (Harbour Lights)``: the Titles are those whose files go to
    the Stragglers' target folders."""
    if not plan.stragglers:
        return "No Stragglers in this Plan."
    targets = {claim_key(s.destination.parent) for s in plan.stragglers}
    names = sorted(
        {
            match_name(e.title, plan.mode)
            for e in plan.entries
            if e.title is not None
            and e.destination is not None
            and claim_key(e.destination.parent) in targets
        },
        key=str.casefold,
    )
    titles = f" ({', '.join(names)})" if names else ""
    return f"Merge {plural(len(plan.stragglers), 'Straggler')}{titles}"


class ApplyConfirm(ConfirmDialog):
    """ "Apply the Plan?" with what Apply will do (:func:`confirm_lines`), and Apply or Back;
    ``enter`` applies too."""

    BINDINGS = [*ConfirmDialog.BINDINGS, Binding("enter", "answer(True)", show=False)]

    def __init__(self, plan: Plan) -> None:
        lines = Content.from_markup("\n".join(confirm_lines(plan)))
        super().__init__("Apply the Plan?", lines, yes="Apply", no="Back")
