"""LLM 客户端测试:用 httpx.MockTransport 注入假网络,不发真请求。

MockTransport 的 handler 长得像真实请求处理函数:收到请求对象、
返回 httpx.Response。在 handler 里可以计数、检查请求头/体、抛异常
模拟网络故障 —— 这是"不联网测网络代码"的标准姿势。
"""
import asyncio

import httpx
import pytest

from researchpilot.errors import LlmError
from researchpilot.llm.client import OpenAICompatibleClient

BASE = "https://llm.example.com"
KEY = "test-key"


def _client(handler, *, max_retries=2, retry_delay=0.0):
    return OpenAICompatibleClient(
        base_url=BASE,
        api_key=KEY,
        model="test-model",
        max_retries=max_retries,
        retry_delay=retry_delay,
        transport=httpx.MockTransport(handler),
    )


def _ok_response(content: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


def test_success_request_shape():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        captured["body"] = request.read()  # bytes,需解码
        return _ok_response()

    asyncio.run(_client(handler).complete("你好", system="你是助手", json_mode=True))

    import json

    body = json.loads(captured["body"])
    assert body["model"] == "test-model"
    assert body["response_format"] == {"type": "json_object"}  # json_mode 生效
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1] == {"role": "user", "content": "你好"}


def test_retry_on_500_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else _ok_response("recovered")

    out = asyncio.run(_client(handler).complete("hi"))
    assert out == "recovered"
    assert calls["n"] == 2  # 第一次 503,重试成功


def test_retries_exhausted_raises_llm_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    with pytest.raises(LlmError):
        asyncio.run(_client(handler).complete("hi"))
    assert calls["n"] == 3  # 首次 + 2 次重试


def test_no_retry_on_400():
    """4xx(除 429)是请求本身错,重试无意义 —— 只调一次。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    with pytest.raises(LlmError):
        asyncio.run(_client(handler).complete("hi"))
    assert calls["n"] == 1


def test_network_error_retries_then_raises():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")  # 模拟断网

    with pytest.raises(LlmError):
        asyncio.run(_client(handler).complete("hi"))
    assert calls["n"] == 3
