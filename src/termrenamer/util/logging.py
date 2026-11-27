"""Stdlib logging setup for bootstrap and TUI, with Provider keys and tokens masked.

Every log record, from any logger and at any level, is made by the record factory
that :func:`mask_secrets_in_logs` installs. The factory masks a key or a token in the
record's message and in its traceback before any handler sees the record, so the
console, the Logs view and any handler added later receive the masked text only.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from typing import Any, TextIO
from urllib.parse import quote

MASK = "***"

_FIELD = re.compile(
    r"""(?ix)
    (?P<name>(?:\b|(?<=_))(?:api_?key|pin|token|access_token|password)\b)
    (?P<sep>=|["']?\s*:\s*["']?)
    (?P<value>[^&\s"',;}]+)
    """
)
"""A secret field: ``api_key=…`` in a query string, ``"apikey": "…"`` in a body."""

_BEARER = re.compile(r"(?i)(\bBearer\s+)[^\s\"',;]+")

_MIN_KNOWN_LENGTH = 6
"""A known secret shorter than this is masked only through :data:`_FIELD`, so a
one-letter stand-in key in a test never masks every such letter of a line."""

_known: set[str] = set()
_lock = threading.Lock()


def keep_out_of_logs(*secrets: str | None) -> None:
    """Mask each of ``secrets``, as written and as a URL writes it, wherever a log line holds it."""
    with _lock:
        for secret in secrets:
            if secret and len(secret) >= _MIN_KNOWN_LENGTH:
                _known.add(secret)
                _known.add(quote(secret, safe=""))


def mask_secrets(text: str) -> str:
    """``text`` with each known secret, secret field and bearer token replaced by ``***``."""
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    text = _FIELD.sub(lambda m: f"{m['name']}{m['sep']}{MASK}", text)
    return _BEARER.sub(lambda m: f"{m[1]}{MASK}", text)


def _masked(record: logging.LogRecord) -> logging.LogRecord:
    try:
        message = record.getMessage()
    except Exception:  # a broken record is the handler's to report, as without masking
        return record
    shown = mask_secrets(message)
    if shown != message:
        record.msg, record.args = shown, None
    if record.exc_info and not record.exc_text:
        record.exc_text = mask_secrets(logging.Formatter().formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = mask_secrets(record.stack_info)
    return record


def mask_secrets_in_logs() -> None:
    """Make every later log record through a factory that masks keys and tokens; idempotent."""
    current = logging.getLogRecordFactory()
    if getattr(current, "masks_secrets", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        return _masked(current(*args, **kwargs))

    factory.masks_secrets = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


def setup_logging(*, level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Configure root logger for console output (default INFO), keys and tokens masked."""
    mask_secrets_in_logs()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )
    root.addHandler(handler)
    root.setLevel(level)
