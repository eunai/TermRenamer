"""Shared synchronous HTTP client with bounded retries (docs/project_spec.md §12.4)."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from termrenamer.util.errors import ProviderError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpClientConfig:
    """Transport knobs aligned with spec §12.4–§12.5."""

    timeout_seconds: float = 30.0
    max_attempts: int = 4
    backoff_base_seconds: float = 0.5
    jitter: bool = True
    max_backoff_seconds: float = 60.0


class HttpClient:
    """Thin wrapper around ``httpx.Client`` with retry/backoff (no secrets in logs)."""

    def __init__(
        self,
        *,
        config: HttpClientConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config or HttpClientConfig()
        timeout = httpx.Timeout(self._config.timeout_seconds)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Perform an HTTP request with retries; map exhaustion to ``ProviderError``.

        Retries on: timeout, connect errors, HTTP 429 / 502 / 503 / 504.
        Does not retry 401/404/400 (adapters handle auth refresh separately).
        """
        last_error: BaseException | None = None
        for attempt in range(self._config.max_attempts):
            try:
                response = self._client.request(method, url, **kwargs)
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
            ) as exc:
                last_error = exc
                _LOG.debug(
                    "HTTP attempt %s/%s failed (transient): %s",
                    attempt + 1,
                    self._config.max_attempts,
                    type(exc).__name__,
                )
                if attempt + 1 >= self._config.max_attempts:
                    msg = f"HTTP request failed after {self._config.max_attempts} attempts"
                    raise ProviderError(msg) from exc
                self._sleep_before_retry(attempt, retry_after_seconds=None)
                continue

            if response.status_code in (429, 502, 503, 504):
                if attempt + 1 >= self._config.max_attempts:
                    msg = f"HTTP {response.status_code} after {self._config.max_attempts} attempts"
                    raise ProviderError(msg)
                retry_after = _parse_retry_after(response)
                self._sleep_before_retry(attempt, retry_after_seconds=retry_after)
                continue

            return response

        if last_error is not None:
            raise ProviderError("HTTP request failed") from last_error
        raise ProviderError("HTTP request failed")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def _sleep_before_retry(
        self,
        attempt_index: int,
        *,
        retry_after_seconds: float | None,
    ) -> None:
        if retry_after_seconds is not None:
            delay = min(retry_after_seconds, self._config.max_backoff_seconds)
        else:
            base = self._config.backoff_base_seconds * (2**attempt_index)
            delay = min(base, self._config.max_backoff_seconds)
            if self._config.jitter:
                delay = delay * (0.5 + random.random() * 0.5)
        if delay < 0:
            delay = 0.0
        time.sleep(delay)


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        now = time.time()
        return float(max(0.0, dt.timestamp() - now))
    except (OSError, TypeError, ValueError):
        return None
