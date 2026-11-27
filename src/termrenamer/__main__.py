"""``python -m termrenamer`` entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Run the Textual app after loading settings and planning wiring.

    Before the screen takes over the terminal, Poster files older than 30 days are
    deleted and the terminal is checked, once, for images it can draw.
    """
    from termrenamer.tui import poster_support
    from termrenamer.tui.app import TermRenamerApp
    from termrenamer.util.errors import ValidationError
    from termrenamer.wiring import bootstrap_wiring

    try:
        settings, wiring = bootstrap_wiring()
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    if wiring.posters is not None:
        wiring.posters.remove_old()
    support = poster_support.detect_poster_support()
    TermRenamerApp(wiring=wiring, settings=settings, poster_support=support).run()


if __name__ == "__main__":
    main()
