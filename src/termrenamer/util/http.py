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


class Abandoned(ProviderError):
    """A request given up between attempts because its answer is no longer wanted."""


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
        return self._with_retries(lambda: self._client.request(method, url, **kwargs))

    def download(
        self, url: str, *, max_bytes: int, go_on: Callable[[], bool] | None = None
    ) -> Download:
        """GET ``url`` with retries, as :meth:`request` does, reading at most ``max_bytes``.

        Redirects are not followed, and the request carries only the client's default
        headers. A body longer than ``max_bytes`` stops the read and raises
        ``ProviderError``, as does any status but 200. Before each attempt after the
        first, ``go_on`` is asked whether the answer is still wanted; when it says no,
        the download raises :class:`Abandoned` without sending again.
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

        response = self._with_retries(send, go_on)
        if response.status_code != 200:
            raise ProviderError(f"HTTP {response.status_code}")
        return Download(
            content=bytes(body),
            content_type=response.headers.get("Content-Type", ""),
        )

    def _with_retries(
        self, send: Callable[[], httpx.Response], go_on: Callable[[], bool] | None = None
    ) -> httpx.Response:
        last_error: BaseException | None = None
        for attempt in range(self._config.max_attempts):
            if attempt and go_on is not None and not go_on():
                raise Abandoned("given up before another attempt: no longer wanted")
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
