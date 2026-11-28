"""The Undo confirm: nothing is put back until the person answers yes.

It returns ``True`` for ``y`` and ``False`` for ``n`` or Escape. It sits where the Apply
confirm sits. Its lines are plain text.
"""

from __future__ import annotations

from textual.content import Content

from termrenamer.core.models import ApplyOutcome
from termrenamer.tui.dialogs.confirm import ConfirmDialog
from termrenamer.tui.words import agree, plural


def undo_lines(outcome: ApplyOutcome) -> tuple[str, ...]:
    """What the confirm says: the videos and Sidecars put back, the Stragglers that go
    back with them, the folders made again, and the folders Apply made, which Undo
    removes when it leaves them empty; each line only when it counts any.

    A file is told from a Straggler's by its recorded old path, as text: an entry's is
    the source of one of the outcome's results.
    """
    entries = {str(result.source) for result in outcome.results}
    files = sum(1 for move in outcome.moves if str(move.source) in entries)
    # Each Straggler's moved file is the Straggler itself, or a file inside it.
    moved = {
        str(path)
        for move in outcome.moves
        if str(move.source) not in entries
        for path in (move.source, *move.source.parents)
    }
    stragglers = sum(1 for result in outcome.stragglers if str(result.source) in moved)
    folders = len(outcome.folders_removed)
    lines = []
    if files:
        lines.append(
            f"Put {plural(files, 'file')} back where {agree(files, 'it was', 'they were')}."
        )
    if stragglers and files:
        lines.append(
            "The Straggler goes back too."
            if stragglers == 1
            else f"The {stragglers} Stragglers go back too."
        )
    elif stragglers:
        them = agree(stragglers, "it was", "they were")
        lines.append(f"Put {plural(stragglers, 'Straggler')} back where {them}.")
    if folders:
        lines.append(
            "The removed folder is made again."
            if folders == 1
            else f"The {folders} removed folders are made again."
        )
    if made := len(outcome.folders_created):
        lines.append(
            "Remove the folder Apply made, when it is empty."
            if made == 1
            else f"Remove the {made} folders Apply made, when they are empty."
        )
    return tuple(lines)


class UndoConfirm(ConfirmDialog):
    """ "Undo the last Apply?" with what Undo will do (:func:`undo_lines`), and Put back
    or Keep."""

    def __init__(self, outcome: ApplyOutcome) -> None:
        lines = Content("\n".join(undo_lines(outcome)))
        super().__init__("Undo the last Apply?", lines, yes="Put back", no="Keep")
