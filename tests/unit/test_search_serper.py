"""Serper 检索测试:MockTransport 注入假网络。"""
import asyncio

import httpx
import pytest

from researchpilot.errors import SearchError
from researchpilot.search.providers import SerperSearch


def _client(handler, *, max_retries=2, retry_delay=0.0):
    return SerperSearch(
        api_key="k",
        max_retries=max_retries,
        retry_delay=retry_delay,
        transport=httpx.MockTransport(handler),
    )


def _organic():
    return {"organic": [
        {"title": "Result One", "link": "https://one.io", "snippet": "snip one"},
        {"title": "Result Two", "link": "https://two.io", "snippet": "snip two"},
    ]}


def test_search_returns_sources_and_sends_key():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "google.serper.dev"
        assert request.headers["X-API-KEY"] == "k"
        return httpx.Response(200, json=_organic())

    out = asyncio.run(_client(handler).search("深度学习", top_k=5))
    assert [s.title for s in out] == ["Result One", "Result Two"]
    assert out[0].url == "https://one.io"
    assert out[0].snippet == "snip one"


def test_top_k_limits_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_organic())

    out = asyncio.run(_client(handler).search("q", top_k=1))
    assert len(out) == 1


def test_retry_on_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json=_organic())

    out = asyncio.run(_client(handler).search("q"))
    assert len(out) == 2
    assert calls["n"] == 2


def test_retries_exhausted_raises_search_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with pytest.raises(SearchError):
        asyncio.run(_client(handler).search("q"))
    assert calls["n"] == 3


def test_400_no_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(SearchError):
        asyncio.run(_client(handler).search("q"))
    assert calls["n"] == 1
