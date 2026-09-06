"""Writer 单测:JSON 提取 / 引用消毒 / 重试 / 证据不足小节。"""
import asyncio
import json

import pytest

from researchpilot.core.report import CitedSource, SectionDraft
from researchpilot.core.writer import Writer, _sanitize_citations
from researchpilot.errors import WritingError
from tests.fakes import FakeLLM

MD = "# 报告\n\n第一节 [1] 内容 [2]。\n\n第二节 [3] 引用。"
GOOD = json.dumps({"report_md": MD})  # 用 dumps 生成,别手拼 JSON(换行转义极易错)

POOL = [
    CitedSource(citation_no=1, url="https://a.io", title="A"),
    CitedSource(citation_no=2, url="https://b.io", title="B"),
    CitedSource(citation_no=3, url="https://c.io", title="C"),
]

SECTIONS = [
    SectionDraft(sub_index=0, question="Q0", claim="c0", citation_nos=[1, 2]),
    SectionDraft(sub_index=1, question="Q1", claim="c1", citation_nos=[3]),
]


def _write(llm, sections=SECTIONS):
    return asyncio.run(Writer(llm=llm).write("主题", sections, POOL))


def test_write_returns_markdown():
    llm = FakeLLM(script=[GOOD])
    md = _write(llm)
    assert md == MD
    # 模型必须拿到引用表(url 提供出处)与各节可用编号
    prompt = llm.calls[0]["prompt"]
    assert "https://a.io" in prompt and "[1]" in prompt
    assert llm.calls[0]["json_mode"] is True


def test_accepts_fenced_output():
    fenced = "```json\n" + GOOD + "\n```"
    md = _write(FakeLLM(script=[fenced]))
    assert "[1]" in md


def test_retries_once_then_succeeds():
    llm = FakeLLM(script=["not json", GOOD])
    md = _write(llm)
    assert md == MD
    assert llm.call_count == 2


def test_twice_failure_raises_writing_error():
    with pytest.raises(WritingError):
        _write(FakeLLM(script=["junk", "junk"]))


def test_sanitize_replaces_out_of_range_citations():
    md = "见 [1] 与 [2] 以及越界的 [99] 与 [0]。"
    cleaned = _sanitize_citations(md, max_no=2)
    assert cleaned == "见 [1] 与 [2] 以及越界的 [?] 与 [?]。"


def test_insufficient_section_gets_marked_in_prompt():
    """证据不足的小节:prompt 必须指示按规则明示,且无可用编号。"""
    insufficient = [
        SectionDraft(sub_index=0, question="Q0", claim="资料不足", insufficient=True)
    ]
    llm = FakeLLM(script=[GOOD])
    _write(llm, sections=insufficient)
    prompt = llm.calls[0]["prompt"]
    assert "【证据不足】" in prompt
    assert "无可用引用编号" in prompt
