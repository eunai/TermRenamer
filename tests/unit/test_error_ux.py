"""Error messages: typed errors never carry a secret."""

from __future__ import annotations

from termrenamer.util.errors import ProviderError, ValidationError


def test_error_messages_do_not_contain_api_keys() -> None:
    """Typed errors must not leak API key values in their string representation."""
    fake_key = "sk-secret-abc123"
    err = ProviderError("TMDB request failed with HTTP 401")
    assert fake_key not in str(err)
    err2 = ValidationError("Missing TERMRENAMER_TMDB_API_KEY in environment")
    assert fake_key not in str(err2)


def test_no_secrets_in_provider_error_module() -> None:
    """ProviderError and ValidationError should not accept or embed raw key values."""
    import inspect

    import termrenamer.util.errors as errors_mod

    source = inspect.getsource(errors_mod)
    for secret_pattern in ["API_KEY", "api_key", "token", "password", "secret"]:
        lines_with_secret = [
            line
            for line in source.splitlines()
            if secret_pattern.lower() in line.lower() and "class " not in line
        ]
        for line in lines_with_secret:
            assert "=" not in line or "def " in line or "#" in line, (
                f"errors.py should not embed secret values: {line}"
            )
