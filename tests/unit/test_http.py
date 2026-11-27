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


@pytest.mark.parametrize("value", ["²", "٢"])
def test_retry_after_with_digits_other_than_0_to_9_falls_back_to_backoff(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("termrenamer.util.http.time.sleep", delays.append)

    def handler(request: httpx.Request) -> httpx.Response:
        if not delays:
            return httpx.Response(429, headers=[(b"Retry-After", value.encode())])
        return httpx.Response(200)

    config = HttpClientConfig(max_attempts=2, backoff_base_seconds=0.25, jitter=False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as raw:
        response = HttpClient(config=config, client=raw).get("https://example.test/r")
    assert response.status_code == 200
    assert delays == [0.25]


@pytest.mark.parametrize("value", ["²", "٢"])
def test_download_with_a_length_in_digits_other_than_0_to_9_reads_the_body(value: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=[(b"Content-Length", value.encode())], content=b"abc")

    with httpx.Client(transport=httpx.MockTransport(handler)) as raw:
        download = HttpClient(config=HttpClientConfig(max_attempts=1), client=raw).download(
            "https://example.test/p.jpg", max_bytes=10
        )
    assert download.content == b"abc"


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 307, 308])
@pytest.mark.parametrize("follows", [False, True])
def test_a_redirect_is_a_failure_that_names_the_status_and_host_only(
    status: int, follows: bool
) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(status, headers={"Location": "https://elsewhere.example/x"})

    raw = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=follows)
    client = HttpClient(config=HttpClientConfig(max_attempts=3), client=raw)
    with pytest.raises(ProviderError) as caught:
        client.get("https://example.test/r", params={"api_key": "fake-key-0000"})
    with pytest.raises(ProviderError) as downloaded:
        client.download("https://example.test/p.jpg?sig=fake-sig-0000", max_bytes=10)

    for error in (caught.value, downloaded.value):
        assert str(error) == f"HTTP {status} redirect from example.test not followed"
    assert hosts == ["example.test", "example.test"]


def test_an_own_client_does_not_follow_redirects() -> None:
    client = HttpClient()
    try:
        assert client._client.follow_redirects is False
    finally:
        client.close()


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
