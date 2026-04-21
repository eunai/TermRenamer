"""Typed errors aligned with docs/project_spec.md §5.5."""


class TermRenamerError(Exception):
    """Base for user- and operator-meaningful failures."""


class ParseError(TermRenamerError):
    """Filename did not yield usable TV/film hints."""


class ProviderError(TermRenamerError):
    """HTTP, auth, rate limit, or invalid response from a metadata provider."""


class CacheError(TermRenamerError):
    """SQLite or schema failure."""


class ApplyError(TermRenamerError):
    """Permission, missing path, or cross-device edge cases during apply."""


class ValidationError(TermRenamerError):
    """Config or path failed validation."""
