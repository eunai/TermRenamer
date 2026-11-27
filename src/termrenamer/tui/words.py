"""How the screen writes its recurring words: counts, lists, the Mode and the Providers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath

from termrenamer.core.models import (
    PROVIDER_NAMES,
    Candidate,
    EntryStatus,
    PlanEntry,
    ScanMode,
    Title,
)


def noun(n: int, word: str) -> str:
    """``word``, with an ``s`` unless ``n`` is 1: ``Stage``, ``Stages``."""
    return word if n == 1 else f"{word}s"


def agree(n: int, one: str, many: str) -> str:
    """``one`` when ``n`` is 1, else ``many``: ``moves`` or ``move``, ``its`` or ``their``."""
    return one if n == 1 else many


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


def title_name(name: str, year: int | None, mode: ScanMode) -> str:
    """A Title as the list writes it: a film with its year, a show by its name alone."""
    return f"{name} ({year})" if mode is ScanMode.FILM and year is not None else name


def match_name(match: Candidate | Title, mode: ScanMode) -> str:
    return title_name(match.name, match.year, mode)


def why_not_renamed(entry: PlanEntry) -> str | None:
    """Why Apply will not rename ``entry``, as the footer, the Apply confirm and the
    Applied Stage write it; ``None`` when Apply will rename it.

    A Sidecar has its video's status, so it gives its video's reason.
    """
    if entry.status is EntryStatus.LEFT_OUT:
        return "left out, so Apply does not touch it"
    if entry.status is EntryStatus.NOT_RECOGNISED:
        return "not recognised: its name could not be read"
    if entry.status is EntryStatus.NO_MATCH:
        if entry.title is not None and entry.title.match is not None:
            return "no match: the episode was not found"
        return f"no match: the {'film' if entry.season is None else 'show'} was not found"
    if entry.skipped_for_name_taken:
        return "name taken, so it stays where it is"
    if entry.has_its_name:
        return "already has its name"
    return None


def folder_text(folder: PurePath) -> str:
    """``folder`` ending in one separator of its own system: ``/media/Shows/``, ``D:\\Shows\\``."""
    text = str(folder)
    sep = folder.parser.sep
    return text if text.endswith(sep) else text + sep


def sidecar_skipped(source: PurePath, reason: str) -> str:
    """The Apply confirm's line for a Sidecar skipped while its video moves."""
    return f"Sidecar skipped: {source.name} · {reason}"
