"""研究阶段集成测试:Fake 全链路下,并行跑完多个子问题。

Mock 环境没有任何真实网络/LLM —— 这是"逻辑层集成",
验证 runner 编排、Researcher、解析、模型组装互相咬合。
"""
import asyncio

import pytest

from researchpilot.core.models import SubQuestion
from researchpilot.core.research import run_research_phase
from researchpilot.errors import ResearchError
from tests.fakes import FakeLLM, FakeSearch, fake_fetch

NOTE_JSON = '{"claim": "子问题结论", "details": "见 [0]。", "source_indexes": [0]}'


def test_parallel_phase_returns_all_notes_in_order():
    subs = [
        SubQuestion(index=i, question=f"Q{i}", queries=[f"q{i}"]) for i in range(5)
    ]
    search = FakeSearch({
        f"q{i}": [{"url": f"https://s{i}.io", "title": f"S{i}"}] for i in range(5)
    })
    contents = {f"https://s{i}.io": f"内容{i}" for i in range(5)}
    llm = FakeLLM(script=[NOTE_JSON] * 5)  # 5 个子问题各调 1 次 LLM

    notes = asyncio.run(run_research_phase(
        subs, llm=llm, search=search, fetch=fake_fetch(contents), max_concurrent=3
    ))

    assert len(notes) == 5
    # gather 保序:notes[i] 对应 subs[i]
    assert [n.sub_index for n in notes] == [0, 1, 2, 3, 4]
    assert all(len(n.sources) == 1 for n in notes)
    assert notes[0].sources[0].content == "内容0"
    # 两条检索词都被执行
    assert search.queries == ["q0", "q1", "q2", "q3", "q4"]
    assert llm.call_count == 5


def test_phase_propagates_hard_failure():
    """任何子问题失败(LLM 输出连续坏)都让整体失败,不静默产出残缺报告。"""
    subs = [SubQuestion(index=0, question="Q0", queries=["q0"])]
    llm = FakeLLM(script=["bad json"] * 2)
    search = FakeSearch({"q0": [{"url": "https://s.io", "title": "S"}]})

    with pytest.raises(ResearchError):
        asyncio.run(run_research_phase(
            subs, llm=llm, search=search,
            fetch=fake_fetch({"https://s.io": "c"}),
            max_concurrent=1,
        ))
