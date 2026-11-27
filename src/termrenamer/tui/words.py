"""How the screen writes its recurring words: counts, lists, the Mode and the Providers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath

from termrenamer.core.models import PROVIDER_NAMES, EntryStatus, PlanEntry, ScanMode


def noun(n: int, word: str) -> str:
    """``word``, with an ``s`` unless ``n`` is 1: ``Stage``, ``Stages``."""
    return word if n == 1 else f"{word}s"


def plural(n: int, word: str) -> str:
    """``n`` and ``word``, with an ``s`` unless ``n`` is 1: ``1 Title``, ``2 Titles``."""
    return f"{n} {noun(n, word)}"


def and_list(names: Sequence[str]) -> str:
    """``Queue, Preview and Applied``."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def mode_label(mode: ScanMode) -> str:
    """``TV`` or ``Film``."""
    return "TV" if mode is ScanMode.TV else "Film"


def provider_name(provider_id: str) -> str:
    """The Provider's name as the screen writes it, such as ``TheTVDB`` for ``tvdb``."""
    return PROVIDER_NAMES.get(provider_id, provider_id)


def folder_text(folder: PurePath) -> str:
    """``folder`` ending in one separator of its own system: ``/media/Shows/``, ``D:\\Shows\\``."""
    text = str(folder)
    sep = folder.parser.sep
    return text if text.endswith(sep) else text + sep


def name_taken_note(entry: PlanEntry) -> str | None:
    """What Apply does with ``entry`` because its name is taken; ``None`` when it is not.

    With a numbered name (Name taken set to ``suffix``) it is renamed to that name;
    without one (``skip``) Apply skips it.
    """
    if entry.status is not EntryStatus.NAME_TAKEN:
        return None
    if entry.destination is None:
        return "Name taken: Apply skips it, and it stays where it is."
    return f"Name taken: it gets a number, as {entry.destination.name}."
