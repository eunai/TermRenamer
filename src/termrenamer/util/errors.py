"""Typed errors for TermRenamer failures."""

from termrenamer.util.logging import mask_secrets


class TermRenamerError(Exception):
    """Base for user- and operator-meaningful failures."""


class ParseError(TermRenamerError):
    """Filename did not yield usable TV/film hints."""


class ProviderError(TermRenamerError):
    """HTTP, auth, rate limit, or invalid response from a metadata provider.

    Its message is masked as it is made: each Provider key and token registered with
    :func:`~termrenamer.util.logging.keep_out_of_logs` is written ``***``, so a server
    that echoes a request's key in its error shows the mask on every screen that
    shows the message, as in the logs.
    """

    def __init__(self, *args: object) -> None:
        super().__init__(*(mask_secrets(arg) if isinstance(arg, str) else arg for arg in args))


class CacheError(TermRenamerError):
    """SQLite or schema failure."""


class ApplyError(TermRenamerError):
    """Permission, missing path, or cross-device edge cases during apply."""


class ValidationError(TermRenamerError):
    """Config or path failed validation."""
