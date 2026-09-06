"""检索服务提供方:协议 + 两个实现。

架构:
- Researcher 只依赖 SearchProvider 协议,不知道背后是哪个服务商
- 生产默认 Serper(免费额度足够 demo,返回结构化 JSON 质量稳定)
- DuckDuckGo 是零 key 兜底:任何环境都能跑(代价:HTML 接口偶发
  反爬、质量不稳) —— 宁可慢/弱,不可没有

实现纪律:所有错误包装成 SearchError(上层统一处理),不泄漏 httpx 异常。
"""
import asyncio
import logging
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..core.models import SearchSource
from ..errors import SearchError

logger = logging.getLogger(__name__)


class SearchProvider(Protocol):
    """内核检索所依赖的最小接口。"""

    async def search(self, query: str, top_k: int = 5) -> list[SearchSource]:
        """返回按相关度排序的来源(不含正文,正文由 fetch 单独抓取)。"""
        ...


class SerperSearch:
    """serper.dev 的 Google 搜索(结构化 JSON,每 query 一次 POST)。"""

    ENDPOINT = "https://google.serper.dev/search"

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 2,
        retry_delay: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._transport = transport

    async def search(self, query: str, top_k: int = 5) -> list[SearchSource]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._search_once(query, top_k)
            except _RetryableSearchError as e:
                last_error = e
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (2**attempt))

        raise SearchError(f"Serper 检索失败(重试耗尽): {last_error}")

    async def _search_once(self, query: str, top_k: int) -> list[SearchSource]:
        async with httpx.AsyncClient(transport=self._transport) as client:
            try:
                resp = await client.post(
                    self.ENDPOINT,
                    json={"q": query},
                    headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                    timeout=15.0,
                )
            except (httpx.TransportError, httpx.TimeoutException) as e:
                raise _RetryableSearchError(f"网络错误: {e}") from e

            if resp.status_code in (429, 500, 502, 503, 504):
                raise _RetryableSearchError(f"上游限流/错误: HTTP {resp.status_code}")
            if resp.status_code >= 400:
                raise SearchError(
                    f"Serper 拒绝请求: HTTP {resp.status_code} {resp.text[:200]}"
                )

            try:
                organic = resp.json().get("organic", [])
            except ValueError as e:
                raise SearchError(f"Serper 响应不是合法 JSON: {e}") from e

            out: list[SearchSource] = []
            for item in organic[:top_k]:
                url = (item.get("link") or "").strip()
                title = (item.get("title") or "").strip()
                snippet = (item.get("snippet") or "").strip()
                if url and title:
                    out.append(SearchSource(url=url, title=title, snippet=snippet))
            return out


class DuckDuckGoSearch:
    """DuckDuckGo HTML 版零 key 兜底实现。

    HTML 接口的 DOM 结构不对外承诺,故解析写成纯函数 _parse_ddg_html
    单独单测 —— 结构变了只改这一个函数。
    """

    ENDPOINT = "https://html.duckduckgo.com/html/"

    async def search(self, query: str, top_k: int = 5) -> list[SearchSource]:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (researchpilot demo)"},
                timeout=15.0,
            ) as client:
                resp = await client.get(self.ENDPOINT, params={"q": query})
        except (httpx.TransportError, httpx.TimeoutException) as e:
            raise SearchError(f"DDG 网络错误: {e}") from e
        if resp.status_code >= 400:
            raise SearchError(f"DDG 请求失败: HTTP {resp.status_code}")
        return _parse_ddg_html(resp.text)[:top_k]


# -- DDG 结果页解析(纯函数,便于单测) --------------------------------------

class _DdgResultParser(HTMLParser):
    """只关心两类元素:标题链接(result__a)与摘要(result__snippet)。"""

    def __init__(self) -> None:
        super().__init__()
        self._in_link = False
        self._in_snippet = False
        self._href: str | None = None
        self._buf: list[str] = []
        self.results: list[SearchSource] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls = attrs.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._in_link, self._href = True, attrs.get("href")
            self._buf = []
        elif tag == "a" and "result__snippet" in cls:
            self._in_snippet = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "a" and (self._in_link or self._in_snippet):
            text = "".join(self._buf).strip()
            if self._in_link:
                url = _resolve_ddg_url(self._href or "")
                if url and text:
                    self.results.append(SearchSource(url=url, title=text))
            elif self._in_snippet and self.results:
                self.results[-1].snippet = text
            self._in_link = self._in_snippet = False

    def handle_data(self, data):
        if self._in_link or self._in_snippet:
            self._buf.append(data)


def _resolve_ddg_url(href: str) -> str:
    """DDG 链接是 /l/?uddg=<urlencode(真实URL)>,解出真实地址。"""
    if "uddg=" in href:
        parsed = parse_qs(urlparse(href).query)
        if parsed.get("uddg"):
            return unquote(parsed["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_html(html: str) -> list[SearchSource]:
    parser = _DdgResultParser()
    try:
        parser.feed(html)
    except Exception:  # HTML 再畸形也不能让解析器崩溃
        logger.warning("DDG 结果页解析异常,返回空结果")
        return []
    return parser.results


class _RetryableSearchError(Exception):
    """内部标记:值得重试的检索失败。"""
