"""Shared synchronous HTTP client with bounded retries."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from termrenamer.util.errors import ProviderError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpClientConfig:
    """Transport knobs: timeout, retry attempts and backoff."""

    timeout_seconds: float = 30.0
    max_attempts: int = 4
    backoff_base_seconds: float = 0.5
    jitter: bool = True
    max_backoff_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class Download:
    """A downloaded body and the ``Content-Type`` it came with (blank when none)."""

    content: bytes
    content_type: str


class HttpClient:
    """Thin wrapper around ``httpx.Client`` with retry/backoff.

    Each response it returns is logged at INFO with the method, the host and the path
    of the request as the caller made it, and the status: never the query string, which
    holds the TMDB and OMDb keys, and never a URL a server sent back, such as a
    redirect's. httpx's own request lines are kept out of the logs
    (:mod:`termrenamer.util.logging`). No other line of it quotes a URL, a header or a
    body.
    """

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
        response = self._with_retries(lambda: self._client.request(method, url, **kwargs))
        _log_answer(method, url, response)
        return response

    def download(self, url: str, *, max_bytes: int) -> Download:
        """GET ``url`` with retries, as :meth:`request` does, reading at most ``max_bytes``.

        Redirects are not followed, and the request carries only the client's default
        headers. A body longer than ``max_bytes`` stops the read and raises
        ``ProviderError``, as does any status but 200.
        """

        too_large = f"Download larger than {max_bytes} bytes"
        body = bytearray()

        def send() -> httpx.Response:
            body.clear()
            with self._client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code != 200:
                    return response
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise ProviderError(too_large)
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ProviderError(too_large)
                return response

        response = self._with_retries(send)
        _log_answer("GET", url, response)
        if response.status_code != 200:
            raise ProviderError(f"HTTP {response.status_code}")
        return Download(
            content=bytes(body),
            content_type=response.headers.get("Content-Type", ""),
        )

    def _with_retries(self, send: Callable[[], httpx.Response]) -> httpx.Response:
        last_error: BaseException | None = None
        for attempt in range(self._config.max_attempts):
            try:
                response = send()
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


def _log_answer(method: str, url: str, response: httpx.Response) -> None:
    """Log the request as the caller made it: its method, host and path, and the status."""
    asked = httpx.URL(url)
    _LOG.info(
        "HTTP %s %s://%s%s %s", method, asked.scheme, asked.host, asked.path, response.status_code
    )


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
