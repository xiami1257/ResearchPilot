"""Researcher 单测:FakeSearch + fake_fetch + FakeLLM,零网络。

重点验证防幻觉的机制:模型只能看到提供的来源、只能引用编号、
证据不足路径可走通。
"""
import asyncio

import pytest

from researchpilot.core.models import SubQuestion
from researchpilot.core.researcher import Researcher
from researchpilot.errors import ResearchError, SearchError
from tests.fakes import FakeLLM, FakeSearch, fake_fetch

GOOD = """{"claim": "结论一", "details": "依据 [0] 与 [2]。", "source_indexes": [0, 2]}"""


def _sub(n: int = 0, queries=("q1", "q2")) -> SubQuestion:
    return SubQuestion(index=n, question=f"问题{n}", queries=list(queries))


def _search_map():
    """两条检索词,每条各返回 2 个来源(共 4 个,去重后仍 4 个)。"""
    return {
        "q1": [
            {"url": "https://a.com/1", "title": "A1", "snippet": "sa1"},
            {"url": "https://a.com/2", "title": "A2", "snippet": "sa2"},
        ],
        "q2": [
            {"url": "https://b.com/1", "title": "B1", "snippet": "sb1"},
            {"url": "https://b.com/2", "title": "B2", "snippet": "sb2"},
        ],
    }


def _contents():
    return {
        "https://a.com/1": "A1 正文内容", "https://a.com/2": "A2 正文内容",
        "https://b.com/1": "B1 正文内容", "https://b.com/2": "B2 正文内容",
    }


def _research(llm, search=None, contents=None):
    search = search or FakeSearch(_search_map())
    fetch = fake_fetch(contents if contents is not None else _contents())
    return asyncio.run(Researcher(llm=llm, search=search, fetch=fetch).research_one(_sub()))


def test_research_returns_note_with_sources_and_evidence():
    llm = FakeLLM(script=[GOOD])
    note = _research(llm)

    assert note.sub_index == 0
    assert note.claim == "结论一"
    assert note.evidence_indexes == [0, 2]
    assert len(note.sources) == 4  # 检索结果全部收录,正文已填充
    assert note.sources[0].content == "A1 正文内容"
    # 模型必须看到每个来源的 URL(才能"引用",否则无从核验)
    prompt = llm.calls[0]["prompt"]
    assert "https://a.com/1" in prompt and "https://b.com/2" in prompt
    assert llm.calls[0]["json_mode"] is True


def test_fetch_failure_falls_back_to_snippet():
    """抓取失败的来源:content 留空保留(Reviewer 会看到),不崩溃。"""
    llm = FakeLLM(script=[GOOD])
    contents = {"https://a.com/1": "A1 正文内容"}  # 其余 URL 抓取失败
    note = _research(llm, contents=contents)

    assert len(note.sources) == 4
    failed = [s for s in note.sources if s.url == "https://a.com/2"][0]
    assert failed.content == ""  # 正文缺失但来源仍在(带 snippet)
    assert failed.snippet == "sa2"


def test_empty_search_results_allows_honest_no_evidence_note():
    """检索零结果:模型应能输出"证据不足",而不是编造。"""
    llm = FakeLLM(script=[
        '{"claim": "现有公开资料不足以回答该子问题", "details": "", "source_indexes": []}'
    ])
    search = FakeSearch({})  # 任何 query 都无结果
    note = _research(llm, search=search)

    assert note.evidence_indexes == []
    assert "不足以" in note.claim


def test_out_of_range_index_retries_then_success():
    llm = FakeLLM(script=[
        '{"claim": "x", "details": "", "source_indexes": [99]}',  # 越界 -> 触发重试
        GOOD,
    ])
    note = _research(llm)
    assert note.evidence_indexes == [0, 2]
    assert llm.call_count == 2
    assert "越界" in (llm.calls[1]["system"] or "")


def test_twice_bad_raises_research_error():
    llm = FakeLLM(script=['{"claim": "x", "details": "", "source_indexes": [999]}'] * 2)
    with pytest.raises(ResearchError):
        _research(llm)


class _FlakySearch:
    """包装真 FakeSearch:q2 检索词模拟上游故障(抛 SearchError)。"""

    def __init__(self, inner):
        self._inner = inner

    async def search(self, query: str, top_k: int = 5):
        if query == "q2":
            raise SearchError("模拟上游限流")
        return await self._inner.search(query, top_k)


def test_search_failure_on_one_query_is_degraded():
    """单条检索词抛错(限流等)不应杀死整个子问题。"""
    # 降级后只剩 q1 的 2 个来源(编号 0..1),剧本必须与之匹配
    llm = FakeLLM(script=[
        '{"claim": "降级结论", "details": "", "source_indexes": [0, 1]}'
    ])
    search = _FlakySearch(FakeSearch(_search_map()))
    note = asyncio.run(
        Researcher(llm=llm, search=search, fetch=fake_fetch(_contents())).research_one(_sub())
    )
    assert len(note.sources) == 2  # 只有 q1 的来源
    assert note.claim == "降级结论"


def test_non_search_error_is_not_swallowed():
    """编程错误(这里模拟协议被破坏)必须上抛,不能被降级吞掉。"""
    llm = FakeLLM(script=[GOOD])

    class Broken:
        async def search(self, query: str, top_k: int = 5):
            raise AttributeError("search 实现写错了")  # noqa: TRY002 模拟 bug

    with pytest.raises(AttributeError):
        asyncio.run(
            Researcher(llm=llm, search=Broken(), fetch=fake_fetch(_contents())).research_one(_sub())
        )
