"""``python -m termrenamer`` entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Run the Textual app after loading settings and planning wiring."""
    from termrenamer.tui.app import TermRenamerApp
    from termrenamer.util.errors import ValidationError
    from termrenamer.wiring import bootstrap_wiring

    try:
        settings, wiring = bootstrap_wiring()
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    TermRenamerApp(wiring=wiring, settings=settings).run()


if __name__ == "__main__":
    main()
