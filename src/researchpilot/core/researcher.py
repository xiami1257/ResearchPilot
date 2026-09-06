"""Researcher:对单个子问题做「检索 → 读网页 → 提炼带证据笔记」。

防幻觉的第一道闸在这里(Reviewer 是第二道):
- 模型**永远看不到真实 URL 生成指令** —— 它的信息来源只能是
  prompt 里编号的来源清单,输出只能用编号引用,不得自造 URL
- 证据不足就明确输出空 evidence(claim 也如实说明),不硬编

结构注意:research_one 只处理"一个子问题",不关心并行。
并行由 research.py 的 runner 用 asyncio 编排 —— 单测时逐个测,
集成时测并行,两个维度都干净。
"""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from ..errors import ResearchError, SearchError
from ..llm.client import LLMClient
from .models import Note, SearchSource, SubQuestion

logger = logging.getLogger(__name__)

# 单个来源进 prompt 的正文上限(字符):6 个来源 × 2k ≈ 12k 字符,量级可控
_CONTENT_CAP = 2000
# 每个检索词只抓前几个来源的全文(避免来源膨胀、token 失控)
_FETCH_PER_QUERY = 3

# 注入的 fetch 类型:url -> 正文或 None
FetchFn = Callable[[str], Awaitable[str | None]]

SYSTEM_PROMPT = """\
你是一个研究助手,负责把一个子问题研究清楚,产出结构化笔记。
你会收到若干编号的网页来源(真实抓取内容),只能基于这些来源作答。

只输出一个 JSON 对象,不要 markdown 代码块,不要任何解释:
{"claim": "...", "details": "...", "source_indexes": [0, 2]}

规则:
- claim: 一句话、可被事实核验的主张,必须能被列出的来源直接支撑
- details: 用来源中的具体信息展开论证,需要提来源时用 [n] 引用其编号
- source_indexes: 支撑 claim 的来源编号列表
  —— 若没有任何来源足以支撑任何主张,输出空列表 [],并让 claim
     如实说明"现有资料不足以回答",严禁编造信息
- 严禁生成来源之外的 URL、数字、人名或任何事实:编造即失败
"""

RETRY_SUFFIX = (
    "\n\n注意:你上次的输出无法解析(原因: {error})。"
    "请重新输出一个合法 JSON 对象。"
)


class Researcher:
    """一个子问题的研究者。依赖全部注入:llm / search / fetch。"""

    def __init__(self, llm: LLMClient, search, fetch: FetchFn) -> None:
        self._llm = llm
        self._search = search
        self._fetch = fetch

    async def research_one(self, sub: SubQuestion) -> Note:
        """完整研究一个子问题:检索 → 抓正文 → LLM 提炼 → 校验。"""
        sources = await self._collect_sources(sub)

        prompt = self._build_prompt(sub, sources)
        error: str | None = None
        for attempt in range(2):  # 与 Planner 相同:一次自纠机会
            system = SYSTEM_PROMPT + (
                "" if error is None else RETRY_SUFFIX.format(error=error)
            )
            raw = await self._llm.complete(prompt, system=system, json_mode=True)
            try:
                claim, details, indexes = _parse_note_output(raw, len(sources))
                return Note(
                    sub_index=sub.index,
                    claim=claim,
                    details=details,
                    sources=sources,
                    evidence_indexes=indexes,
                )
            except ValueError as e:
                error = str(e)
                logger.warning(
                    "Researcher 输出解析失败(第 %s 次, sub=%s): %s",
                    attempt + 1,
                    sub.index,
                    error,
                )

        raise ResearchError(f"子问题 {sub.index} 的笔记提炼连续两次失败: {error}")

    # -- 内部 -------------------------------------------------------------

    async def _collect_sources(self, sub: SubQuestion) -> list[SearchSource]:
        """逐条检索词搜索;抓取每个结果的正文(并行);按 URL 去重。"""
        raw: list[SearchSource] = []
        for query in sub.queries:
            try:
                hits = await self._search.search(query, top_k=_FETCH_PER_QUERY)
            except SearchError as e:
                # 单条检索词失败不致命:降级继续(有其它 query 兜底)。
                # 注意只接 SearchError:编程错误(AttributeError 之类)
                # 必须立刻上抛暴露,不能被静默吞掉掩盖 bug。
                logger.warning("检索词失败 %r: %s", query, e)
                continue
            raw.extend(hits)

        # 按 URL 去重(同一页面常被不同 query 命中),保持首次出现顺序
        seen: set[str] = set()
        sources: list[SearchSource] = []
        for s in raw:
            if s.url not in seen:
                seen.add(s.url)
                sources.append(s)

        # 并行抓取所有正文 —— 一次子问题的多个页面同时下载,
        # 一个慢页面的超时不会拖慢其它页面(见 extract.py 短超时策略)
        contents = await _fetch_all(self._fetch, [s.url for s in sources])
        for s, content in zip(sources, contents):
            if content is not None:
                s.content = content
        return sources

    def _build_prompt(self, sub: SubQuestion, sources: list[SearchSource]) -> str:
        lines = [f"子问题: {sub.question}", "", "可用来源(编号即引用依据):"]
        if not sources:
            lines.append("(没有检索到任何来源)")
        for i, s in enumerate(sources):
            body = s.content or s.snippet or "(抓取失败,仅剩摘要)"
            body = body if len(body) <= _CONTENT_CAP else body[:_CONTENT_CAP]
            lines.append(f"\n[{i}] 标题: {s.title}\n    地址: {s.url}\n    内容: {body}")
        lines.append("\n请输出研究笔记 JSON。")
        return "\n".join(lines)


async def _fetch_all(fetch: FetchFn, urls: list[str]) -> list[str | None]:
    """并行抓取,单个页面任何异常都吞掉返回 None(不拖垮整体)。"""

    async def safe(url: str) -> str | None:
        try:
            return await fetch(url)
        except Exception as e:
            logger.warning("页面抓取异常 %s: %s", url, e)
            return None

    return list(await asyncio.gather(*(safe(u) for u in urls)))


def _parse_note_output(raw: str, n_sources: int) -> tuple[str, str, list[int]]:
    """解析笔记 JSON,校验来源编号不越界。坏输出抛 ValueError(带原因)。"""
    text = _strip_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"非法 JSON: {e}") from e

    claim = str(data.get("claim", "")).strip()
    if not claim:
        raise ValueError("缺少 claim")
    details = str(data.get("details", "")).strip()

    indexes = data.get("source_indexes", [])
    if not isinstance(indexes, list):
        raise ValueError("source_indexes 必须是数组")
    clean: list[int] = []
    for x in indexes:
        if isinstance(x, bool) or not isinstance(x, int):  # bool 是 int 子类,单独排除
            raise ValueError(f"source_indexes 含非整数: {x!r}")
        if not 0 <= x < n_sources:
            raise ValueError(f"来源编号 {x} 越界(可用 0..{n_sources - 1})")
        clean.append(x)
    return claim, details, clean


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()
