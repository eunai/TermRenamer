"""Stdlib logging setup for bootstrap and TUI, keeping Provider keys and tokens out.

Two layers keep a secret out of the log lines:

1. At the source. httpx logs each request's full URL, query string and key included,
   at INFO; :func:`quiet_request_urls` sets its loggers to WARNING, and
   :class:`~termrenamer.util.http.HttpClient` logs each request's URL without its
   query instead. No message of the app quotes a request's URL, headers or body.
   This is the only layer for a short secret, such as TheTVDB's subscriber PIN.
2. A net. :class:`MaskingFormatter` writes ``***`` in place of each value given to
   :func:`keep_out_of_logs` in the final text of each line, traceback and stack
   included, so a message, a traceback or another library that quotes a key or a
   token anyway shows the mask. A value shorter than :data:`MIN_MASKED_LENGTH` is
   not masked, so a short value never changes a year or a word of a line.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TextIO
from urllib.parse import quote

MASK = "***"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

MIN_MASKED_LENGTH = 8
"""The shortest value :func:`keep_out_of_logs` masks. Provider keys and tokens are
longer; a shorter value would mask ordinary text."""

_REQUEST_LOGGERS = ("httpx", "httpcore")

_known: set[str] = set()
_lock = threading.Lock()


def keep_out_of_logs(*secrets: str | None) -> None:
    """Mask each of ``secrets`` at least :data:`MIN_MASKED_LENGTH` long, as written and
    as a URL writes it, in every line a :class:`MaskingFormatter` writes."""
    with _lock:
        for secret in secrets:
            if secret and len(secret) >= MIN_MASKED_LENGTH:
                _known.add(secret)
                _known.add(quote(secret, safe=""))


def mask_secrets(text: str) -> str:
    """``text`` with each value given to :func:`keep_out_of_logs` replaced by ``***``."""
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    return text


class MaskingFormatter(logging.Formatter):
    """A formatter whose every line, traceback and stack included, has the known secrets
    masked. A record that cannot be formatted gives a line that says so, never an error."""

    def __init__(self, fmt: str = LOG_FORMAT) -> None:
        super().__init__(fmt)

    def format(self, record: logging.LogRecord) -> str:
        try:
            text = super().format(record)
        except Exception as exc:  # noqa: BLE001 - a log line must never raise into the caller
            text = f"{record.levelname} {record.name}: a log line could not be written ({exc})"
        return mask_secrets(text)


def quiet_request_urls() -> None:
    """Keep httpx's request lines, which hold each request's full URL, out of the logs."""
    for name in _REQUEST_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(*, level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Configure root logger for console output (default INFO), keys and tokens kept out."""
    quiet_request_urls()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(MaskingFormatter())
    root.addHandler(handler)
    root.setLevel(level)
