"""LLM 客户端:OpenAI 兼容协议封装(httpx 直连,不依赖官方 SDK)。

设计要点:

1. **接口最小化 + 依赖注入。** 内核的 Planner/Researcher 只认识
   `LLMClient` 协议的两个方法;真实现(OpenAICompatibleClient)在构造
   时才注入配置。这样测试可以传 FakeLLM(剧本式假实现),而
   httpx 层自己用 MockTransport 单测 —— 两层互不拖累。

2. **异步。** M2 起多个 Researcher 并行各占一个 LLM 调用,
   同步阻塞会杀死并发,所以 M1 就定 async 接口。

3. **容错分层:**
   - 网络错误 / 5xx / 429:重试(指数退避,默认最多重试 2 次)
   - 4xx(除 429):请求本身错了,重试无意义,直接抛 LlmError
   - 响应缺字段:按"上游协议异常"抛 LlmError,由调用方决定是否降级
"""
import asyncio
import logging
from typing import Protocol

import httpx

from ..errors import LlmError

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """内核依赖的最小 LLM 接口。"""

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """发一次补全请求,返回文本。json_mode=True 时要求模型输出 JSON。"""
        ...


class OpenAICompatibleClient:
    """OpenAI 兼容 chat/completions 实现(DeepSeek/通义/GLM 均适用)。

    transport 参数只用于测试注入(MockTransport),生产不传。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "deepseek-chat",
        timeout: float = 60.0,
        max_retries: int = 2,
        retry_delay: float = 0.6,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._transport = transport

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict = {"model": self._model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._post_once(body)
            except _RetryableError as e:
                last_error = e
                logger.warning("LLM 调用失败(第 %s 次):%s", attempt + 1, e)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (2**attempt))

        raise LlmError(f"LLM 调用重试耗尽: {last_error}")

    # -- 内部 -----------------------------------------------------------

    async def _post_once(self, body: dict) -> str:
        # 每次请求一个短生命周期 client,省去资源管理问题;
        # 生产并发场景可换成模块级共享 client(性能优化,行为不变)。
        async with httpx.AsyncClient(transport=self._transport) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
            except (httpx.TransportError, httpx.TimeoutException) as e:
                raise _RetryableError(f"网络错误: {e}") from e

            if resp.status_code in (429, 500, 502, 503, 504):
                raise _RetryableError(f"上游限流/服务错误: HTTP {resp.status_code}")
            if resp.status_code >= 400:
                raise LlmError(
                    f"LLM 请求被拒绝: HTTP {resp.status_code} "
                    f"{resp.text[:300]}"
                )

            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise LlmError(f"LLM 响应结构异常: {e}") from e


class _RetryableError(Exception):
    """仅用于类内部:标记"值得重试"的失败。"""
