"""Tavily 检索测试:MockTransport 注入假网络(与 test_search_serper 同构)。"""
import asyncio

import httpx
import pytest

from researchpilot.errors import SearchError
from researchpilot.search.providers import TavilySearch


def _client(handler, *, max_retries=2, retry_delay=0.0):
    return TavilySearch(
        api_key="k",
        max_retries=max_retries,
        retry_delay=retry_delay,
        transport=httpx.MockTransport(handler),
    )


def _results():
    return {"results": [
        {"title": "Result One", "url": "https://one.io", "content": "body one"},
        {"title": "Result Two", "url": "https://two.io", "content": "body two"},
    ]}


def test_search_returns_sources_and_sends_bearer():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tavily.com"
        assert request.headers["Authorization"] == "Bearer k"
        # top_k 必须传给 max_results(async 请求体要用 aread 读;httpx JSON 无空格)
        body = (await request.aread()).decode()
        assert '"max_results":5' in body
        return httpx.Response(200, json=_results())

    out = asyncio.run(_client(handler).search("深度学习", top_k=5))
    assert [s.title for s in out] == ["Result One", "Result Two"]
    assert out[0].url == "https://one.io"
    assert out[0].snippet == "body one"


def test_long_content_truncated_to_snippet():
    long_body = "x" * 2000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"title": "T", "url": "https://t.io", "content": long_body},
        ]})

    out = asyncio.run(_client(handler).search("q"))
    assert len(out[0].snippet) == TavilySearch.SNIPPET_MAX


def test_top_k_limits_results_and_request():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = (await request.aread()).decode()
        assert '"max_results":1' in body
        return httpx.Response(200, json=_results())

    out = asyncio.run(_client(handler).search("q", top_k=1))
    assert len(out) == 1


def test_retry_on_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json=_results())

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


def test_missing_results_key_is_ok():
    """Tavily 无结果时返回空 results,不是错误。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": "q"})

    out = asyncio.run(_client(handler).search("q"))
    assert out == []
