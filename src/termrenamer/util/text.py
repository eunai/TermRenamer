"""Small checks on text read from a Provider's answer."""

from __future__ import annotations


def plain_digits(text: str) -> bool:
    """Return whether ``text`` is one or more of the digits ``0`` to ``9`` and nothing else.

    ``str.isdigit`` also accepts digits such as ``"²"`` or ``"٢"``, which ``int`` reads
    wrongly or refuses with an error.
    """
    return text.isascii() and text.isdigit()
