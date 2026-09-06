"""Reviewer 单测:确定性预检 / LLM 判定 / 降级策略。"""
import asyncio

from researchpilot.core.events import Verdict
from researchpilot.core.models import Note, SearchSource
from researchpilot.core.reviewer import Reviewer
from tests.fakes import FakeLLM

GOOD = """{"reviews": [
    {"index": 0, "verdict": "supported", "reason": "来源直接说明"},
    {"index": 1, "verdict": "unsupported", "reason": "与主张无关"}
]}"""


def _note(evidence_indexes=(0, 1), *, empty_idx=()) -> Note:
    """构造笔记:索引 0/1 来源有内容,empty_idx 里的来源抓取失败(空)。"""
    sources = []
    for i in range(2):
        if i in empty_idx:
            sources.append(SearchSource(url=f"https://x{i}.io", title=f"X{i}"))  # 无内容无摘要
        else:
            sources.append(SearchSource(url=f"https://x{i}.io", title=f"X{i}", content=f"内容{i}"))
    return Note(sub_index=0, claim="主张", details="细节", sources=sources, evidence_indexes=list(evidence_indexes))


def _review(llm, note=None):
    return asyncio.run(Reviewer(llm=llm).review_note(note or _note()))


def test_llm_verdicts_are_collected():
    llm = FakeLLM(script=[GOOD])
    result = _review(llm)

    assert result.sub_index == 0
    assert result.verdict_of(0) == Verdict.SUPPORTED
    assert result.verdict_of(1) == Verdict.UNSUPPORTED
    # 模型必须看到来源内容(核验依据)
    prompt = llm.calls[0]["prompt"]
    assert "https://x0.io" in prompt and "内容0" in prompt


def test_all_empty_sources_skips_llm_entirely():
    llm = FakeLLM(script=[])
    result = _review(llm, note=_note(evidence_indexes=(0, 1), empty_idx=(0, 1)))
    assert len(result.evidence) == 2
    assert all(r.verdict is Verdict.UNVERIFIABLE for r in result.evidence)
    assert llm.call_count == 0  # 没有任何可核内容,一次 LLM 都不调


def test_out_of_set_index_triggers_retry():
    llm = FakeLLM(script=[
        '{"reviews": [{"index": 7, "verdict": "supported", "reason": "x"}]}',  # 发明编号
        GOOD,
    ])
    result = _review(llm)
    assert result.verdict_of(0) == Verdict.SUPPORTED
    assert llm.call_count == 2
    assert "不在可核验集合" in (llm.calls[1]["system"] or "")


def test_twice_failure_degrades_to_unverifiable_not_raise():
    """核验失败降级(设计取舍):全部标 UNVERIFIABLE,不抛错。"""
    llm = FakeLLM(script=["bad json", "still bad"])
    result = _review(llm)
    assert all(r.verdict is Verdict.UNVERIFIABLE for r in result.evidence)
    assert "无法解析" in result.evidence[0].reason


def test_review_prompt_only_lists_candidates():
    """prompt 只列可核验候选(空来源不进模型视野,省 token)。"""
    llm = FakeLLM(script=[
        '{"reviews": [{"index": 0, "verdict": "supported", "reason": "r"}]}'
    ])
    _review(llm, note=_note(empty_idx=(1,)))
    prompt = llm.calls[0]["prompt"]
    assert "[0]" in prompt and "https://x0.io" in prompt
    assert "https://x1.io" not in prompt  # 已自动判死的来源不进 prompt
