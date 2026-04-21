"""Stdlib logging setup for bootstrap and TUI."""

from __future__ import annotations

import logging
import sys
from typing import TextIO


def setup_logging(*, level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Configure root logger for console output (default INFO)."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )
    root.addHandler(handler)
    root.setLevel(level)
