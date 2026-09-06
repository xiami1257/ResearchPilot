"""报告素材组装(纯逻辑,零 I/O):核验结果 → 引用池 + 各节草稿。

这是"防幻觉第三道闸"的确定性部分:
- 只有被 Reviewer 判 SUPPORTED 的来源才能进入全局引用池、被 Writer 引用
- UNSUPPORTED / UNVERIFIABLE 的来源一律进不了报告正文
- 没有任何合格证据的子问题节被标记 insufficient,Writer 必须如实写"证据不足"

全流程无 LLM 调用 —— 纯函数最好测,规则定死在这里,
不让模型参与"哪些引用合格"这类高 stakes 的裁决。
"""
from pydantic import BaseModel, Field

from .events import Verdict
from .models import Note, NoteReview, SubQuestion


class CitedSource(BaseModel):
    """全局引用池中的一条(报告脚注表的原料)。用 pydantic:可序列化落库。"""

    citation_no: int
    url: str
    title: str


class SectionDraft(BaseModel):
    """报告的一个小节素材(对应一个研究子问题)。"""

    sub_index: int
    question: str
    claim: str
    details: str = ""
    citation_nos: list[int] = Field(default_factory=list)
    insufficient: bool = False


def build_report_sources(
    subquestions: list[SubQuestion],
    notes: list[Note],
    reviews: list[NoteReview],
) -> tuple[list[SectionDraft], list[CitedSource]]:
    """把三份产物合成 Writer 的输入;返回 (sections, 引用池)。

    引用编号按 notes 顺序、证据顺序全局连续分配 [1..M]。
    注意:notes 与 reviews 必须按下标一一对应(调用方保证)。
    """
    review_by_sub = {r.sub_index: r for r in reviews}

    sections: list[SectionDraft] = []
    pool: list[CitedSource] = []
    next_no = 1

    for note in notes:
        review = review_by_sub.get(note.sub_index)
        supported: list[int] = []
        if review is not None:
            # 只有明确 SUPPORTED 的才入池
            supported = [
                er.index for er in review.evidence if er.verdict is Verdict.SUPPORTED
            ]

        citation_nos: list[int] = []
        for i in supported:
            src = note.sources[i]
            pool.append(CitedSource(citation_no=next_no, url=src.url, title=src.title))
            citation_nos.append(next_no)
            next_no += 1

        insufficient = len(citation_nos) == 0
        sections.append(SectionDraft(
            sub_index=note.sub_index,
            question=_question_of(subquestions, note.sub_index),
            claim=note.claim,
            details=note.details,
            citation_nos=citation_nos,
            insufficient=insufficient,
        ))

    return sections, pool


def _question_of(subquestions: list[SubQuestion], sub_index: int) -> str:
    for s in subquestions:
        if s.index == sub_index:
            return s.question
    return f"子问题 {sub_index}"  # 防御:笔记与子问题表对不上时仍可继续


_REF_HEADING = "## 引用来源"


def render_references(md: str, pool: list[CitedSource]) -> str:
    """在报告文末拼上确定性引用脚注表(带 URL)。

    为什么由代码拼而不是让模型写(核心卖点的最后一环):
    URL 与编号的对应是"核验通过后的事实",模型重述一遍只会引入
    出错机会(漏写、编号错位、格式漂移)。规则 5 明令模型别写,
    这里 100% 确定性地落一份。若报告已含该标题行(旧模型行为
    或人为注入)则不重复追加 —— 幂等。
    """
    if not pool or _REF_HEADING in md:
        return md
    lines = ["", _REF_HEADING, ""]
    for c in pool:
        if c.title:
            lines.append(f"[{c.citation_no}] {c.title} — {c.url}")
        else:
            lines.append(f"[{c.citation_no}] {c.url}")
    return md.rstrip() + "\n" + "\n".join(lines) + "\n"
