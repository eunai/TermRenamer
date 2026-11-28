"""The Apply confirm: nothing is renamed until the person answers yes.

It returns ``True`` for ``y`` or ``enter`` and ``False`` for ``n`` or Escape. It sits
over the Title list, right of where the Poster panel goes.
"""

from __future__ import annotations

from collections import Counter

from textual.binding import Binding
from textual.content import Content

from termrenamer.core.models import EntryStatus, Plan, ScanMode
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


def confirm_lines(plan: Plan) -> tuple[Content, ...]:
    """What the confirm says: the videos renamed and where, the videos
    skipped counted by status, the videos left out, each Sidecar skipped while its
    video moves, those that already have their names, with Folder rename on the
    Stragglers to merge and the Titles they go with, and that nothing has been renamed
    yet."""
    counts = PlanCounts.of(plan)
    where = _where(plan, counts.to_rename)
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
        Content.from_markup(
            f"[$foreground]Rename {plural(counts.to_rename, 'video')} $where.[/]", where=where
        ),
        Content.from_markup(f"[$foreground]{skip}[/]"),
    ]
    if counts.left_out:
        them = agree(counts.left_out, "it", "them")
        lines.append(
            Content.from_markup(
                f"[$foreground]Leave out {plural(counts.left_out, 'video')}: "
                f"Apply does not touch {them}.[/]"
            )
        )
    for sidecar in sidecars_skipped_alone(plan):
        reason = why_not_renamed(sidecar) or sidecar.status.value
        line = sidecar_skipped(sidecar.source, reason)
        lines.append(Content.from_markup("[$tr-dim]$line[/]", line=line))
    if named:
        that = agree(len(named), "that already has its name", "that already have their names")
        lines.append(
            Content.from_markup(f"[$tr-dim]Leave {plural(len(named), 'video')} {that}.[/]")
        )
    if plan.options.folder_rename:
        lines.append(Content.from_markup("[$tr-dim]$line[/]", line=_merge_line(plan)))
    lines += [Content(), Content.from_markup("[$warning]Nothing has been renamed yet.[/]")]
    return tuple(lines)


def _where(plan: Plan, videos: int) -> str:
    """Where the Plan puts its videos, as the templates lay them out: in their own
    folders while Folder rename is off; otherwise into show (and season) or film
    folders, under the Destination root or, with none, in the folders they were queued
    from."""
    options = plan.options
    if not options.folder_rename:
        return agree(videos, "in its own folder", "in their own folders")
    if plan.mode is ScanMode.FILM:
        folders = agree(videos, "into a film folder", "into film folders")
    elif options.season_folders:
        folders = "into show and season folders"
    else:
        folders = "into show folders"
    root = options.destination_root
    if root is not None:
        return f"{folders} under {folder_text(root)}"
    return f"{folders} in the {agree(videos, 'folder it was', 'folders they were')} queued from"


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
        lines = Content("\n").join(confirm_lines(plan))
        super().__init__("Apply the Plan?", lines, yes="Apply", no="Back")
