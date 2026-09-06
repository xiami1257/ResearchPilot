"""报告环节集成:Fake LLM 下跑通 核验 -> 组装 -> 成稿 全链条。

覆盖"一半合格一半证据不足"的真实形态,验证防幻觉闸门协作:
Reviewer 判定 -> report 只放行 SUPPORTED -> Writer 明示不足节。
"""
import asyncio

from researchpilot.core.models import Note, SearchSource, SubQuestion
from researchpilot.core.report import build_report_sources
from researchpilot.core.reviewer import run_review_phase
from researchpilot.core.writer import Writer
from tests.fakes import FakeLLM

# 两个子问题的笔记:
#   sub0 引用两条来源(A 真支撑 / B 无关)
#   sub1 引用一条来源(C,内容单薄)
NOTES = [
    Note(
        sub_index=0, claim="主张甲",
        sources=[
            SearchSource(url="https://a.io", title="A", content="支撑甲的内容"),
            SearchSource(url="https://b.io", title="B", content="完全无关的别的话题"),
        ],
        evidence_indexes=[0, 1],
    ),
    Note(
        sub_index=1, claim="主张乙",
        sources=[SearchSource(url="https://c.io", title="C", content="几行泛泛而谈")],
        evidence_indexes=[0],
    ),
]

SUBS = [
    SubQuestion(index=0, question="甲是什么", queries=["q"]),
    SubQuestion(index=1, question="乙是什么", queries=["q"]),
]

# 剧本序列:Reviewer(sub0) -> Reviewer(sub1) -> Writer
REVIEW_SUB0 = (
    '{"reviews": [{"index": 0, "verdict": "supported", "reason": "内容确实支撑"},'
    ' {"index": 1, "verdict": "unsupported", "reason": "内容与主张无关"}]}'
)
REVIEW_SUB1 = (
    '{"reviews": [{"index": 0, "verdict": "unverifiable", "reason": "内容过于单薄"}]}'
)
WRITE_JSON = (
    '{"report_md": "# 主题报告\\n\\n## 关于甲\\n\\n甲是… [1]。\\n\\n'
    '## 关于乙\\n\\n> 证据不足:乙的公开资料不足以支撑结论。\\n\\n"}'
)


def test_full_report_flow():
    llm = FakeLLM(script=[REVIEW_SUB0, REVIEW_SUB1, WRITE_JSON])

    async def flow():
        reviews = await run_review_phase(NOTES, llm=llm)
        sections, pool = build_report_sources(SUBS, NOTES, reviews)

        # 闸门生效:只有 SUPPORTED 的 A 进池;UNSUPPORTED 的 B 与
        # UNVERIFIABLE 的 C 都被排除;乙节因此标记为证据不足
        assert len(pool) == 1
        assert pool[0].citation_no == 1 and pool[0].url == "https://a.io"
        assert sections[0].insufficient is False
        assert sections[0].citation_nos == [1]
        assert sections[1].insufficient is True

        md = await Writer(llm=llm).write("主题报告", sections, pool)
        return md, pool

    md, pool = asyncio.run(flow())

    assert "[1]" in md  # Writer 用了合法编号
    assert "证据不足" in md  # 乙节被如实标注
    assert llm.call_count == 3  # 2 次核验 + 1 次写作
