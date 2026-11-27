"""How the screen writes its recurring words: counts, lists, the Mode and the Providers."""

from __future__ import annotations

from collections.abc import Sequence

from termrenamer.core.models import ScanMode

_PROVIDER_NAMES = {"tmdb": "TMDB", "tvdb": "TheTVDB", "omdb": "OMDb"}


def plural(n: int, word: str) -> str:
    """``n`` and ``word``, with an ``s`` unless ``n`` is 1: ``1 Title``, ``2 Titles``."""
    return f"{n} {word}{'' if n == 1 else 's'}"


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
    return _PROVIDER_NAMES.get(provider_id, provider_id)
