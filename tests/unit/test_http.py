"""Contract tests for util/http retry policy (no live network)."""

from __future__ import annotations

import httpx
import pytest

from termrenamer.util.errors import ProviderError
from termrenamer.util.http import HttpClient, HttpClientConfig


def test_429_twice_then_200_exercises_backoff() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(
        max_attempts=5,
        backoff_base_seconds=0.01,
        jitter=False,
        max_backoff_seconds=1.0,
    )
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        response = client.get("https://example.test/resource")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 3


def test_timeout_then_success() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(
        max_attempts=3,
        backoff_base_seconds=0.01,
        jitter=False,
    )
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        response = client.get("https://example.test/x")
    assert response.status_code == 200
    assert response.text == "ok"
    assert len(calls) == 2


def test_401_not_retried_returns_immediately() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=5, backoff_base_seconds=0.01, jitter=False)
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        response = client.get("https://example.test/protected")
    assert response.status_code == 401
    assert len(calls) == 1


def test_retry_after_header_used(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("termrenamer.util.http.time.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if len(delays) == 0:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(max_attempts=3, backoff_base_seconds=99.0, jitter=False)
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        response = client.get("https://example.test/r")
    assert response.status_code == 200
    assert delays and delays[0] == pytest.approx(2.0, rel=0.01)


def test_max_attempts_exhausted_on_repeated_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(
        max_attempts=2,
        backoff_base_seconds=0.0,
        jitter=False,
        max_backoff_seconds=0.0,
    )
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        with pytest.raises(ProviderError, match="HTTP 429"):
            client.get("https://example.test/r")


def test_connect_error_exhausts_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    transport = httpx.MockTransport(handler)
    config = HttpClientConfig(
        max_attempts=2,
        backoff_base_seconds=0.0,
        jitter=False,
        max_backoff_seconds=0.0,
    )
    with httpx.Client(transport=transport) as raw:
        client = HttpClient(config=config, client=raw)
        with pytest.raises(ProviderError, match="after 2 attempts"):
            client.get("https://example.test/x")
