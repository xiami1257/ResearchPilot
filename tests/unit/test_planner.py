"""Planner 测试:FakeLLM 驱动,零网络。

覆盖:正常解析 / 代码围栏剥离 / 坏 JSON 一次自纠 / 连续失败抛错 / 数量夹取。
"""
import asyncio

import pytest

from researchpilot.core.planner import Planner
from researchpilot.errors import PlanningError
from tests.fakes import FakeLLM

GOOD_JSON = """{"subquestions": [
    {"question": "Q1", "queries": ["q1a", "q1b"]},
    {"question": "Q2", "queries": ["q2a"]},
    {"question": "Q3", "queries": []}
]}"""


def _plan(llm: FakeLLM, topic: str = "测试主题", n_sub: int = 3):
    return asyncio.run(Planner(llm).plan(topic, n_sub=n_sub))


def test_plan_returns_subquestions():
    llm = FakeLLM(script=[GOOD_JSON])
    subs = _plan(llm)

    assert [s.question for s in subs] == ["Q1", "Q2", "Q3"]
    # index 由系统重编
    assert [s.index for s in subs] == [0, 1, 2]
    # queries 为空时退化为问题本身
    assert subs[2].queries == ["Q3"]
    # json_mode 必须被开启
    assert llm.calls[0]["json_mode"] is True


def test_strips_markdown_fence():
    fenced = "```json\n" + GOOD_JSON + "\n```"
    subs = _plan(FakeLLM(script=[fenced]))
    assert len(subs) == 3


def test_bad_json_then_good_retries_once():
    """第一次坏输出 → 自纠重试(带错误回传)→ 成功。"""
    llm = FakeLLM(script=["not json at all", GOOD_JSON])
    subs = _plan(llm)
    assert len(subs) == 3
    assert llm.call_count == 2
    # 第二次请求的 system prompt 必须带上上次的解析错误(自纠依据)
    assert "无法解析" in (llm.calls[1]["system"] or "")


def test_twice_bad_raises_planning_error():
    llm = FakeLLM(script=["junk", "still junk"])
    with pytest.raises(PlanningError):
        _plan(llm)


def test_missing_subquestions_key_raises_then_retry():
    """缺关键键也走重试路径。"""
    llm = FakeLLM(script=['{"other": 1}', GOOD_JSON])
    subs = _plan(llm)
    assert len(subs) == 3


def test_n_sub_is_clamped_to_3_5():
    llm = FakeLLM(script=[GOOD_JSON])
    _plan(llm, n_sub=99)  # 不抛错即可;夹取在 prompt 层体现
    assert "99" not in llm.calls[0]["prompt"]  # 不会要求 99 个

    llm2 = FakeLLM(script=[GOOD_JSON])
    _plan(llm2, n_sub=1)  # 下限夹到 3
    assert "1 个子问题" not in llm2.calls[0]["prompt"]
